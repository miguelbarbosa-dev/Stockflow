import hashlib
import hmac
import json
import re
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from urllib.parse import quote

import pandas as pd
import streamlit as st

DB_NAME = "estoque.db"
LIMITE_MIN = date(2000, 1, 1)
LIMITE_MAX = date(2100, 12, 31)

# Credenciais iniciais e ÚNICAS que nascem como administrador
USUARIO_INICIAL = "admin"
SENHA_INICIAL = "Estoque@123"


@contextmanager
def conectar():
    """Conexão curta: confirma (commit) ao sair e SEMPRE fecha, evitando conexões vazando."""
    conn = sqlite3.connect(DB_NAME, timeout=10)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def gerar_hash_senha(senha, salt=None):
    if salt is None:
        salt = secrets.token_hex(16)
    hash_senha = hashlib.pbkdf2_hmac(
        "sha256", senha.encode("utf-8"), salt.encode("utf-8"), 200_000
    ).hex()
    return salt, hash_senha


def verificar_senha(senha, salt, hash_armazenado):
    _, hash_digitado = gerar_hash_senha(senha, salt)
    return hmac.compare_digest(hash_digitado, hash_armazenado)


def criar_tabela():
    with conectar() as conn:
        conn.execute("PRAGMA journal_mode=WAL")  # leituras e escritas não se bloqueiam
        conn.execute("""
            CREATE TABLE IF NOT EXISTS produtos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome TEXT NOT NULL,
                preco REAL NOT NULL CHECK(preco >= 0),
                quantidade INTEGER NOT NULL CHECK(quantidade >= 0),
                criado_em TEXT NOT NULL,
                ncm TEXT,
                lote TEXT,
                fabricacao TEXT,
                validade TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS movimentacoes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                produto_id INTEGER NOT NULL,
                tipo TEXT NOT NULL,
                quantidade INTEGER NOT NULL CHECK(quantidade > 0),
                data TEXT NOT NULL,
                FOREIGN KEY(produto_id) REFERENCES produtos(id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS usuarios (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                login TEXT NOT NULL UNIQUE,
                salt TEXT NOT NULL,
                senha_hash TEXT NOT NULL,
                perfil TEXT NOT NULL DEFAULT 'funcionario',
                criado_em TEXT NOT NULL
            )
        """)

        # Migrações para bancos antigos: só adiciona o que ainda não existe
        def colunas(tabela):
            return {linha[1] for linha in conn.execute(f"PRAGMA table_info({tabela})")}

        if "perfil" not in colunas("usuarios"):
            conn.execute("ALTER TABLE usuarios ADD COLUMN perfil TEXT DEFAULT 'funcionario'")
        existentes = colunas("produtos")
        for coluna in ("ncm", "lote", "fabricacao", "validade"):
            if coluna not in existentes:
                conn.execute(f"ALTER TABLE produtos ADD COLUMN {coluna} TEXT")

        # Índice que acelera a verificação de exclusão e o histórico
        conn.execute("CREATE INDEX IF NOT EXISTS idx_mov_produto ON movimentacoes(produto_id)")

        # Cria a conta inicial SOMENTE se ainda não existir.
        usuario_existente = conn.execute(
            "SELECT id FROM usuarios WHERE login = ?", (USUARIO_INICIAL,)
        ).fetchone()
        if usuario_existente is None:
            salt, senha_hash = gerar_hash_senha(SENHA_INICIAL)
            conn.execute(
                "INSERT INTO usuarios (login, salt, senha_hash, perfil, criado_em) VALUES (?, ?, ?, ?, ?)",
                (USUARIO_INICIAL, salt, senha_hash, 'admin', agora()),
            )


@st.cache_resource(show_spinner=False)
def inicializar_banco():
    """Prepara o banco uma única vez por processo (e não a cada interação na tela)."""
    criar_tabela()
    return True


def agora():
    return datetime.now().strftime("%d/%m/%Y %H:%M")


def autenticar(login, senha):
    with conectar() as conn:
        usuario = conn.execute(
            "SELECT salt, senha_hash, perfil FROM usuarios WHERE login = ?",
            (login.strip(),),
        ).fetchone()

    if usuario is None:
        return False, None
    salt, senha_hash, perfil = usuario
    if verificar_senha(senha, salt, senha_hash):
        return True, perfil
    return False, None


# ---------------------------------------------------------------------
# NCM (Nomenclatura Comum do Mercosul)
# ---------------------------------------------------------------------
ARQUIVO_TABELA_NCM = "ncm_tabela.csv"  # opcional; também aceita ncm_tabela.json


def normalizar_ncm(valor):
    """Mantém só os dígitos ('2106.90.90' -> '21069090')."""
    if valor is None or pd.isna(valor):
        return ""
    return re.sub(r"\D", "", str(valor))


def formatar_ncm(valor):
    n = normalizar_ncm(valor)
    return f"{n[:4]}.{n[4:6]}.{n[6:]}" if len(n) == 8 else n


@st.cache_data(show_spinner=False)
def carregar_tabela_ncm():
    """Tabela oficial (opcional): dict {codigo_8_digitos: descricao}. Vazio se não houver arquivo."""
    base = Path(__file__).resolve().parent
    tabela = {}
    try:
        csv_path, json_path = base / ARQUIVO_TABELA_NCM, base / "ncm_tabela.json"
        if csv_path.exists():
            df = pd.read_csv(csv_path, sep=None, engine="python", dtype=str, encoding_errors="replace")
            registros = df.to_dict("records")
        elif json_path.exists():
            dados = json.loads(json_path.read_text(encoding="utf-8"))
            if isinstance(dados, dict):
                dados = next((v for v in dados.values() if isinstance(v, list)), [])
            registros = dados
        else:
            return tabela
        for reg in registros:
            chaves = {str(k).lower(): v for k, v in reg.items()}
            cod = next((v for k, v in chaves.items() if k.startswith(("cod", "ncm"))), "")
            desc = next((v for k, v in chaves.items() if k.startswith("desc")), "")
            cod = normalizar_ncm(cod)
            if len(cod) == 8:
                tabela[cod] = str(desc)
    except Exception:
        return {}
    return tabela


def validar_ncm(valor):
    """Retorna (ok, mensagem, descricao). Valida formato e, se houver tabela, a existência."""
    n = normalizar_ncm(valor)
    if len(n) != 8:
        return False, "O NCM deve ter 8 dígitos (ex.: 2106.90.90).", None
    capitulo = int(n[:2])
    if capitulo == 0 or capitulo > 97 or capitulo == 77:
        return False, f"NCM inválido: o capítulo {n[:2]} não existe na nomenclatura.", None
    if n[2:4] == "00":
        return False, "NCM inválido: a posição (3º e 4º dígitos) não pode ser 00.", None
    tabela = carregar_tabela_ncm()
    if tabela:
        if n not in tabela:
            return False, "NCM não consta na tabela oficial carregada.", None
        return True, "NCM válido e encontrado na tabela oficial.", tabela[n]
    return True, "Formato válido (tabela oficial não carregada; confira no Siscomex).", None


# ---------------------------------------------------------------------
# Datas e validações de produto
# ---------------------------------------------------------------------
def para_data(valor):
    try:
        return date.fromisoformat(valor) if isinstance(valor, str) and valor else None
    except ValueError:
        return None


def validar_campos_produto(ncm, fabricacao, validade):
    """Retorna a mensagem de erro ou None se estiver tudo certo."""
    if normalizar_ncm(ncm) or str(ncm or "").strip():
        ok, msg, _ = validar_ncm(ncm)
        if not ok:
            return msg
    if fabricacao and fabricacao > date.today():
        return "A data de fabricação não pode ser futura."
    if fabricacao and validade and validade < fabricacao:
        return "A validade não pode ser anterior à fabricação."
    return None


def _formatar_datas(serie):
    return pd.to_datetime(serie, errors="coerce").dt.strftime("%d/%m/%Y").fillna("")


def rotulo_validade(dias):
    if pd.isna(dias):
        return "Sem validade"
    if dias < 0:
        return "Vencido"
    if dias == 0:
        return "Vence hoje"
    return f"Vence em {int(dias)} dia(s)"


# ---------------------------------------------------------------------
# Produtos e movimentações (leituras em cache; escritas limpam o cache)
# ---------------------------------------------------------------------
def _limpar_cache_estoque():
    listar_produtos.clear()
    listar_historico.clear()


@st.cache_data(show_spinner=False)
def listar_produtos():
    with conectar() as conn:
        return pd.read_sql_query(
            "SELECT id, nome, preco, quantidade, ncm, lote, fabricacao, validade "
            "FROM produtos ORDER BY nome",
            conn
        )


@st.cache_data(show_spinner=False)
def listar_historico():
    with conectar() as conn:
        return pd.read_sql_query("""
            SELECT m.id, p.nome AS produto, p.lote, m.tipo, m.quantidade, m.data
            FROM movimentacoes m
            JOIN produtos p ON p.id = m.produto_id
            ORDER BY m.id DESC
            LIMIT 100
        """, conn)


def _campos_extras(ncm, lote, fabricacao, validade):
    return (
        normalizar_ncm(ncm) or None,
        (lote or "").strip() or None,
        fabricacao.isoformat() if fabricacao else None,
        validade.isoformat() if validade else None,
    )


def adicionar_produto(nome, preco, quantidade, ncm="", lote="", fabricacao=None, validade=None):
    with conectar() as conn:
        conn.execute(
            "INSERT INTO produtos (nome, preco, quantidade, criado_em, ncm, lote, fabricacao, validade) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (nome.strip(), float(preco), int(quantidade), agora(),
             *_campos_extras(ncm, lote, fabricacao, validade))
        )
    _limpar_cache_estoque()


def editar_produto(produto_id, nome, preco, quantidade, ncm="", lote="", fabricacao=None, validade=None):
    with conectar() as conn:
        conn.execute(
            "UPDATE produtos SET nome = ?, preco = ?, quantidade = ?, "
            "ncm = ?, lote = ?, fabricacao = ?, validade = ? WHERE id = ?",
            (nome.strip(), float(preco), int(quantidade),
             *_campos_extras(ncm, lote, fabricacao, validade), int(produto_id))
        )
    _limpar_cache_estoque()


def excluir_produto(produto_id):
    with conectar() as conn:
        existe_movimentacao = conn.execute(
            "SELECT 1 FROM movimentacoes WHERE produto_id = ? LIMIT 1", (int(produto_id),)
        ).fetchone()
        if existe_movimentacao:
            return False, "Não é possível excluir: este produto já possui movimentações registradas."
        conn.execute("DELETE FROM produtos WHERE id = ?", (int(produto_id),))
    _limpar_cache_estoque()
    return True, "Produto excluído com sucesso."


def movimentar_estoque(produto_id, tipo, quantidade):
    quantidade, produto_id = int(quantidade), int(produto_id)
    if quantidade <= 0:
        return False, "A quantidade deve ser maior que zero."

    with conectar() as conn:
        # Uma única instrução atômica: evita corrida entre dois usuários ao mesmo tempo
        if tipo == "Entrada":
            cur = conn.execute(
                "UPDATE produtos SET quantidade = quantidade + ? WHERE id = ?",
                (quantidade, produto_id))
        else:
            cur = conn.execute(
                "UPDATE produtos SET quantidade = quantidade - ? WHERE id = ? AND quantidade >= ?",
                (quantidade, produto_id, quantidade))
        if cur.rowcount == 0:
            produto = conn.execute(
                "SELECT quantidade FROM produtos WHERE id = ?", (produto_id,)).fetchone()
            if produto is None:
                return False, "Produto não encontrado."
            return False, f"Estoque insuficiente. Disponível: {int(produto[0])}."
        conn.execute(
            "INSERT INTO movimentacoes (produto_id, tipo, quantidade, data) VALUES (?, ?, ?, ?)",
            (produto_id, tipo, quantidade, agora())
        )
    _limpar_cache_estoque()
    return True, f"{tipo} registrada com sucesso."


# --- Funções de Gerenciamento de Usuários (Apenas Admin) ---

@st.cache_data(show_spinner=False)
def listar_usuarios():
    with conectar() as conn:
        return pd.read_sql_query(
            "SELECT id, login, perfil, criado_em FROM usuarios ORDER BY id", conn)


def obter_id_usuario(login):
    with conectar() as conn:
        linha = conn.execute("SELECT id FROM usuarios WHERE login = ?", (login,)).fetchone()
    return linha[0] if linha else None


def adicionar_usuario(novo_login, nova_senha, novo_perfil):
    with conectar() as conn:
        try:
            salt, senha_hash = gerar_hash_senha(nova_senha)
            conn.execute(
                "INSERT INTO usuarios (login, salt, senha_hash, perfil, criado_em) VALUES (?, ?, ?, ?, ?)",
                (novo_login.strip(), salt, senha_hash, novo_perfil, agora())
            )
        except sqlite3.IntegrityError:
            return False, "Já existe um usuário com este login."
    listar_usuarios.clear()
    return True, "Usuário cadastrado com sucesso."


def alterar_perfil_usuario(usuario_id, novo_perfil):
    with conectar() as conn:
        conn.execute("UPDATE usuarios SET perfil = ? WHERE id = ?", (novo_perfil, int(usuario_id)))
    listar_usuarios.clear()
    return True, "Privilégio alterado com sucesso."


def excluir_usuario(usuario_id, usuario_logado_id):
    with conectar() as conn:
        if int(usuario_id) == int(usuario_logado_id):
            return False, "Você não pode excluir sua própria conta."

        admins = conn.execute("SELECT id FROM usuarios WHERE perfil = 'admin'").fetchall()
        usuario_alvo = conn.execute(
            "SELECT perfil FROM usuarios WHERE id = ?", (int(usuario_id),)).fetchone()

        if usuario_alvo and usuario_alvo[0] == 'admin' and len(admins) <= 1:
            return False, "Não é possível excluir o último administrador do sistema."

        conn.execute("DELETE FROM usuarios WHERE id = ?", (int(usuario_id),))
    listar_usuarios.clear()
    return True, "Usuário excluído com sucesso."


def tela_login():
    st.markdown('<h1 class="main-title">StockFlow</h1>', unsafe_allow_html=True)
    st.write("Entre com seu usuário e senha para acessar o sistema.")

    with st.form("form_login"):
        login = st.text_input("Login")
        senha = st.text_input("Senha", type="password")
        entrar = st.form_submit_button("Entrar", type="primary", use_container_width=True)

    if entrar:
        sucesso, perfil = autenticar(login, senha)
        if sucesso:
            st.session_state["autenticado"] = True
            st.session_state["usuario"] = login.strip()
            st.session_state["perfil"] = perfil
            st.rerun()
        else:
            st.error("Login ou senha incorretos.")


# --- Configuração da Página ---
st.set_page_config(
    page_title="StockFlow",
    page_icon="SF",
    layout="wide",
    initial_sidebar_state="expanded",
)

# =====================================================================
# TEMA (claro / escuro / automático) + estilo do front end
# =====================================================================
OPCOES_TEMA = ["Automático (sistema)", "Claro", "Escuro"]

# Paleta de cada tema. Todo o CSS abaixo consome estas variáveis, então
# trocar de tema é só trocar os valores (nenhuma cor fica "fixa" no CSS).
PALETA_CLARA = {
    "color-scheme": "light",
    "--sf-bg": "#F4F7FB",
    "--sf-surface": "#FFFFFF",
    "--sf-surface-2": "#F8FAFC",
    "--sf-field": "#FFFFFF",
    "--sf-text": "#1E293B",
    "--sf-heading": "#0F172A",
    "--sf-muted": "#64748B",
    "--sf-border": "#E2E8F0",
    "--sf-accent": "#2563EB",
    "--sf-accent-hover": "#1D4ED8",
    "--sf-on-accent": "#FFFFFF",
    "--sf-cyan": "#22D3EE",
    "--sf-shadow": "0 1px 3px rgba(15, 23, 42, 0.08)",
}
PALETA_ESCURA = {
    "color-scheme": "dark",
    "--sf-bg": "#0B1220",
    "--sf-surface": "#121A2B",
    "--sf-surface-2": "#172136",
    "--sf-field": "#0F1727",
    "--sf-text": "#E2E8F0",
    "--sf-heading": "#F8FAFC",
    "--sf-muted": "#94A3B8",
    "--sf-border": "#27344D",
    "--sf-accent": "#3B82F6",
    "--sf-accent-hover": "#60A5FA",
    "--sf-on-accent": "#FFFFFF",
    "--sf-cyan": "#67E8F9",
    "--sf-shadow": "0 1px 3px rgba(0, 0, 0, 0.5)",
}


def _carrinho_svg(opacidade):
    """Carrinho de compras só com contorno (azul + ciano claro), fundo transparente."""
    caminhos = (
        "<circle cx='8' cy='21' r='1'/>"
        "<circle cx='19' cy='21' r='1'/>"
        "<path d='M2.05 2.05h2l2.66 12.42a2 2 0 0 0 2 1.58h9.78a2 2 0 0 0 1.95-1.57l1.65-7.43H5.12'/>"
    )
    svg = (
        "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' "
        "stroke-linecap='round' stroke-linejoin='round'>"
        "<defs><linearGradient id='g' x1='0' y1='0' x2='1' y2='1'>"
        "<stop offset='0' stop-color='#2563EB'/><stop offset='1' stop-color='#67E8F9'/>"
        "</linearGradient></defs>"
        f"<g opacity='{opacidade}'>"
        f"<g stroke='url(#g)' stroke-width='0.55'>{caminhos}</g>"   # contorno azul → ciano
        f"<g stroke='#A5F3FC' stroke-width='0.12'>{caminhos}</g>"    # fio ciano claro por cima
        "</g></svg>"
    )
    return f'url("data:image/svg+xml,{quote(svg)}")'


def _declaracoes(paleta, opacidade_carrinho):
    itens = dict(paleta)
    itens["--sf-cart"] = _carrinho_svg(opacidade_carrinho)
    return ";".join(f"{k}:{v}" for k, v in itens.items())


def _tema_nativo_streamlit():
    """Tema que o próprio Streamlit está usando ('light'/'dark'), se a versão informar."""
    try:
        tipo = st.context.theme.type
        return tipo if tipo in ("light", "dark") else None
    except Exception:
        return None


CSS_BASE = """
html, body, .stApp { color-scheme: inherit; }

/* ---------- Fundo e texto geral ---------- */
.stApp, [data-testid="stAppViewContainer"], [data-testid="stMain"] {
    background-color: var(--sf-bg) !important;
}
[data-testid="stHeader"] { background: transparent !important; }
[data-testid="stHeader"] * { color: var(--sf-muted) !important; }

.stApp, .stApp p, .stApp li, .stApp label,
.stApp [data-testid="stWidgetLabel"] *,
.stApp [data-testid="stMarkdownContainer"] {
    color: var(--sf-text);
}
.stApp [data-testid="stCaptionContainer"],
.stApp [data-testid="stCaptionContainer"] * { color: var(--sf-muted) !important; }
.stApp h1, .stApp h2, .stApp h3, .stApp h4,
.stApp [data-testid="stHeading"] * { color: var(--sf-heading) !important; }
.stApp hr { border-color: var(--sf-border) !important; }

/* ---------- Título principal ---------- */
.main-title {
    font-size: 2.5rem !important;
    font-weight: 800 !important;
    color: var(--sf-heading) !important;
    border-bottom: 3px solid var(--sf-accent);
    padding-bottom: 0.5rem;
    margin-bottom: 1rem;
}
[data-testid="stHeading"] h3 { font-weight: 600; margin-top: 1.5rem; }

/* ---------- Cards de métrica ---------- */
[data-testid="stMetric"] {
    background-color: var(--sf-surface);
    border: 1px solid var(--sf-border);
    border-radius: 10px;
    padding: 15px;
    box-shadow: var(--sf-shadow);
}
[data-testid="stMetricLabel"] * { color: var(--sf-muted) !important; }
[data-testid="stMetricValue"] * { color: var(--sf-heading) !important; }

/* ---------- Formulários ---------- */
[data-testid="stForm"] {
    background-color: var(--sf-surface);
    border: 1px solid var(--sf-border) !important;
    border-radius: 10px;
}

/* ---------- Campos de entrada ---------- */
[data-baseweb="input"], [data-baseweb="base-input"],
[data-baseweb="textarea"], [data-baseweb="select"] > div {
    background-color: var(--sf-field) !important;
    border-color: var(--sf-border) !important;
    color: var(--sf-text) !important;
}
[data-baseweb="input"]:focus-within, [data-baseweb="select"] > div:focus-within {
    border-color: var(--sf-accent) !important;
    box-shadow: 0 0 0 1px var(--sf-accent) !important;
}
.stApp input, .stApp textarea {
    color: var(--sf-text) !important;
    -webkit-text-fill-color: var(--sf-text) !important;
    caret-color: var(--sf-accent);
}
.stApp input::placeholder, .stApp textarea::placeholder {
    color: var(--sf-muted) !important;
    -webkit-text-fill-color: var(--sf-muted) !important;
}
[data-baseweb="select"] * { color: var(--sf-text); }
[data-testid="stNumberInput"] button {
    background-color: var(--sf-surface-2) !important;
    color: var(--sf-text) !important;
    border-color: var(--sf-border) !important;
}
/* Lista suspensa dos selectbox */
[data-baseweb="popover"], [data-baseweb="popover"] > div,
[data-baseweb="menu"], [data-baseweb="popover"] ul {
    background-color: var(--sf-surface) !important;
    color: var(--sf-text) !important;
}
[data-baseweb="popover"] li { color: var(--sf-text) !important; }
[data-baseweb="popover"] li:hover,
[data-baseweb="popover"] li[aria-selected="true"] {
    background-color: var(--sf-surface-2) !important;
}

/* ---------- Abas ---------- */
button[data-baseweb="tab"] { color: var(--sf-muted) !important; }
button[data-baseweb="tab"][aria-selected="true"] { color: var(--sf-accent) !important; }
[data-baseweb="tab-highlight"] { background-color: var(--sf-accent) !important; }
[data-baseweb="tab-border"] { background-color: var(--sf-border) !important; }

/* ---------- Botões ---------- */
[data-testid="stBaseButton-secondary"], [data-testid="stBaseButton-secondaryFormSubmit"],
button[kind="secondary"], button[kind="secondaryFormSubmit"] {
    background-color: var(--sf-surface) !important;
    color: var(--sf-text) !important;
    border: 1px solid var(--sf-border) !important;
}
[data-testid="stBaseButton-secondary"]:hover, [data-testid="stBaseButton-secondaryFormSubmit"]:hover,
button[kind="secondary"]:hover, button[kind="secondaryFormSubmit"]:hover {
    border-color: var(--sf-accent) !important;
    color: var(--sf-accent) !important;
}
[data-testid="stBaseButton-primary"], [data-testid="stBaseButton-primaryFormSubmit"],
button[kind="primary"], button[kind="primaryFormSubmit"] {
    background-color: var(--sf-accent) !important;
    color: var(--sf-on-accent) !important;
    border: 1px solid var(--sf-accent) !important;
}
[data-testid="stBaseButton-primary"]:hover, [data-testid="stBaseButton-primaryFormSubmit"]:hover,
button[kind="primary"]:hover, button[kind="primaryFormSubmit"]:hover {
    background-color: var(--sf-accent-hover) !important;
    border-color: var(--sf-accent-hover) !important;
}
[data-testid="stBaseButton-primary"] *, [data-testid="stBaseButton-primaryFormSubmit"] *,
button[kind="primary"] *, button[kind="primaryFormSubmit"] * { color: var(--sf-on-accent) !important; }

/* Foco visível para navegação por teclado */
.stApp button:focus-visible, .stApp input:focus-visible,
.stApp [role="radio"]:focus-visible {
    outline: 2px solid var(--sf-cyan) !important;
    outline-offset: 2px;
}

/* ---------- Barra lateral: transparente, com carrinho ao fundo ---------- */
[data-testid="stSidebar"],
[data-testid="stSidebar"] > div,
[data-testid="stSidebarContent"],
[data-testid="stSidebarUserContent"],
[data-testid="stSidebarHeader"] {
    background: transparent !important;
}
[data-testid="stSidebar"] {
    background-image: var(--sf-cart) !important;
    background-repeat: no-repeat !important;
    background-position: 50% 58% !important;
    background-size: min(88%, 340px) auto !important;
    border-right: 1px solid var(--sf-border);
}
[data-testid="stSidebar"] * { color: var(--sf-text); }
[data-testid="stSidebar"] h1, [data-testid="stSidebar"] h2,
[data-testid="stSidebar"] h3 { color: var(--sf-heading) !important; }

/* ---------- Telas pequenas ---------- */
@media (max-width: 768px) {
    .main-title { font-size: 1.8rem !important; }
    [data-testid="stMetric"] { padding: 10px; }
    [data-testid="stSidebar"] { background-size: 70% auto !important; }
}
"""


def aplicar_tema():
    """Injeta o CSS conforme a escolha de tema guardada na sessão."""
    escolha = st.session_state.get("tema_visual", OPCOES_TEMA[0])

    if escolha == "Claro":
        raiz = f":root {{ {_declaracoes(PALETA_CLARA, 0.55)} }}"
        efetivo = "light"
    elif escolha == "Escuro":
        raiz = f":root {{ {_declaracoes(PALETA_ESCURA, 0.45)} }}"
        efetivo = "dark"
    else:  # Automático: segue o tema do navegador / sistema operacional
        raiz = (
            f":root {{ {_declaracoes(PALETA_CLARA, 0.55)} }}\n"
            f"@media (prefers-color-scheme: dark) {{ :root {{ {_declaracoes(PALETA_ESCURA, 0.45)} }} }}"
        )
        efetivo = None

    # Tabelas (st.dataframe) são desenhadas em canvas e não obedecem ao CSS.
    # Se o tema escolhido for o oposto do tema nativo do Streamlit, inverte as cores delas.
    extra = ""
    nativo = _tema_nativo_streamlit()
    if efetivo and nativo and efetivo != nativo:
        extra = '[data-testid="stDataFrame"] { filter: invert(1) hue-rotate(180deg); }'

    st.markdown(f"<style>{raiz}\n{CSS_BASE}\n{extra}</style>", unsafe_allow_html=True)


def seletor_tema():
    """Controle para o usuário alternar entre automático, claro e escuro."""
    st.radio("Tema", OPCOES_TEMA, key="tema_visual")


aplicar_tema()

inicializar_banco()

# Bloqueia todas as funcionalidades até o usuário autenticar.
if not st.session_state.get("autenticado", False):
    with st.sidebar:
        st.markdown("### StockFlow")
        seletor_tema()
    tela_login()
    st.stop()

# --- BARRA LATERAL (SIDEBAR) ---
with st.sidebar:
    st.markdown("### StockFlow")
    perfil_display = "Administrador" if st.session_state.get("perfil") == "admin" else "Funcionário"
    st.write(f"👤 Perfil: **{perfil_display}**")
    
    st.divider()
    seletor_tema()
    st.divider()
    if st.button("Sair", use_container_width=True, type="secondary"):
        st.session_state["autenticado"] = False
        st.session_state.pop("usuario", None)
        st.session_state.pop("perfil", None)
        st.rerun()

# 3. Título posicionado no topo da área principal, com alto contraste
st.markdown('<h1 class="main-title">StockFlow</h1>', unsafe_allow_html=True)
st.caption("Sistema moderno e eficiente para gestão de estoque.")

produtos = listar_produtos()
total_produtos = len(produtos)
unidades_estoque = int(produtos["quantidade"].sum()) if not produtos.empty else 0
valor_estoque = float((produtos["preco"] * produtos["quantidade"]).sum()) if not produtos.empty else 0.0

c1, c2, c3 = st.columns(3)
c1.metric("Produtos cadastrados", total_produtos)
c2.metric("Unidades em estoque", unidades_estoque)
c3.metric("Valor estimado do estoque", f"R$ {valor_estoque:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))

# Definição das abas
abas = ["Cadastrar / Editar Produtos", "Entrada e Saída", "Consultar Estoque"]
if st.session_state.get("perfil") == "admin":
    abas.append("🛡️ Gerenciar Usuários")

aba_produtos, aba_movimentacoes, aba_consulta, *aba_usuarios = st.tabs(abas)

# --- ABA PRODUTOS ---
with aba_produtos:
    st.subheader("Cadastrar produto")

    with st.expander("Validador de NCM"):
        ncm_teste = st.text_input("Digite um NCM para conferir", key="ncm_teste", placeholder="Ex.: 2106.90.90")
        if ncm_teste.strip():
            ok_ncm, msg_ncm, desc_ncm = validar_ncm(ncm_teste)
            if ok_ncm:
                st.success(f"NCM {formatar_ncm(ncm_teste)} válido." + (f" {desc_ncm}" if desc_ncm else ""))
                if not desc_ncm:
                    st.caption(msg_ncm)
            else:
                st.error(msg_ncm)

    with st.form("form_cadastro", clear_on_submit=True):
        nome = st.text_input("Nome do produto")
        col1, col2 = st.columns(2)
        preco = col1.number_input("Preço (R$)", min_value=0.0, value=0.0, step=0.5, format="%.2f")
        quantidade = col2.number_input("Quantidade inicial", min_value=0, value=0, step=1)
        ncm = st.text_input("NCM", placeholder="0000.00.00", max_chars=10,
                            help="8 dígitos, com ou sem pontos. Opcional, mas validado se preenchido.")
        cl, cf, cv = st.columns(3)
        lote = cl.text_input("Lote")
        fabricacao = cf.date_input("Fabricação", value=None, min_value=LIMITE_MIN,
                                   max_value=date.today(), format="DD/MM/YYYY")
        validade = cv.date_input("Validade", value=None, min_value=LIMITE_MIN,
                                 max_value=LIMITE_MAX, format="DD/MM/YYYY")
        enviado = st.form_submit_button("Cadastrar produto", type="primary")

        if enviado:
            erro = None if nome.strip() else "Informe o nome do produto."
            erro = erro or validar_campos_produto(ncm, fabricacao, validade)
            if erro:
                st.error(erro)
            else:
                adicionar_produto(nome, preco, quantidade, ncm, lote, fabricacao, validade)
                st.success("Produto cadastrado com sucesso.")
                st.rerun()

    st.divider()
    st.subheader("Editar ou excluir produto")
    produtos = listar_produtos()
    if produtos.empty:
        st.info("Cadastre um produto para poder editá-lo.")
    else:
        opcoes = {f"{i} - {n}": int(i) for i, n in zip(produtos["id"], produtos["nome"])}
        selecionado = st.selectbox("Selecione um produto", list(opcoes.keys()), key="produto_editar")
        produto_id = opcoes[selecionado]
        linha = produtos[produtos["id"] == produto_id].iloc[0]

        with st.form("form_edicao"):
            nome_editado = st.text_input("Nome", value=str(linha["nome"]), key=f"nome_{produto_id}")
            col1, col2 = st.columns(2)
            preco_editado = col1.number_input(
                "Preço (R$)", min_value=0.0, value=float(linha["preco"]), step=0.5,
                format="%.2f", key=f"preco_{produto_id}"
            )
            quantidade_editada = col2.number_input(
                "Quantidade", min_value=0, value=int(linha["quantidade"]), step=1,
                key=f"quantidade_{produto_id}"
            )
            ncm_editado = st.text_input(
                "NCM", value=formatar_ncm(linha["ncm"]), max_chars=10, key=f"ncm_{produto_id}")
            cl, cf, cv = st.columns(3)
            lote_editado = cl.text_input(
                "Lote", value="" if pd.isna(linha["lote"]) else str(linha["lote"]), key=f"lote_{produto_id}")
            fab_editada = cf.date_input(
                "Fabricação", value=para_data(linha["fabricacao"]), min_value=LIMITE_MIN,
                max_value=date.today(), format="DD/MM/YYYY", key=f"fab_{produto_id}")
            val_editada = cv.date_input(
                "Validade", value=para_data(linha["validade"]), min_value=LIMITE_MIN,
                max_value=LIMITE_MAX, format="DD/MM/YYYY", key=f"val_{produto_id}")
            salvar = st.form_submit_button("Salvar alterações")
            if salvar:
                erro = None if nome_editado.strip() else "O nome do produto é obrigatório."
                erro = erro or validar_campos_produto(ncm_editado, fab_editada, val_editada)
                if erro:
                    st.error(erro)
                else:
                    editar_produto(produto_id, nome_editado, preco_editado, quantidade_editada,
                                   ncm_editado, lote_editado, fab_editada, val_editada)
                    st.success("Produto atualizado.")
                    st.rerun()

        # RESTRIÇÃO DE EXCLUSÃO: Apenas Admin
        if st.session_state.get("perfil") == "admin":
            if st.button("🗑️ Excluir produto selecionado", key="excluir_produto", type="secondary"):
                sucesso, msg = excluir_produto(produto_id)
                if sucesso:
                    st.success(msg)
                    st.rerun()
                else:
                    st.error(msg)
        else:
            st.info("🔒 Apenas administradores podem excluir produtos.")

# --- ABA MOVIMENTAÇÕES ---
with aba_movimentacoes:
    st.subheader("Registrar entrada ou saída")
    produtos = listar_produtos()
    if produtos.empty:
        st.info("Cadastre um produto antes de registrar movimentações.")
    else:
        opcoes_mov = {}
        for i, n, q, lt in zip(produtos["id"], produtos["nome"], produtos["quantidade"], produtos["lote"]):
            rotulo = f"{n}{'' if pd.isna(lt) or not lt else f' · Lote {lt}'} (estoque: {int(q)})"
            if rotulo in opcoes_mov:  # nomes repetidos não podem se sobrepor
                rotulo += f" [ID {i}]"
            opcoes_mov[rotulo] = int(i)
        with st.form("form_movimentacao"):
            escolha = st.selectbox("Produto", list(opcoes_mov.keys()))
            tipo = st.radio("Tipo de movimentação", ["Entrada", "Saída"], horizontal=True)
            qtd_mov = st.number_input("Quantidade", min_value=1, value=1, step=1)
            registrar = st.form_submit_button("Registrar movimentação", type="primary")
            if registrar:
                sucesso, mensagem = movimentar_estoque(opcoes_mov[escolha], tipo, qtd_mov)
                if sucesso:
                    st.success(mensagem)
                    st.rerun()
                else:
                    st.error(mensagem)

    st.divider()
    st.subheader("Histórico de movimentações")
    historico = listar_historico()
    if historico.empty:
        st.info("Nenhuma movimentação registrada.")
    else:
        st.dataframe(historico.fillna(""), use_container_width=True, hide_index=True)

# --- ABA CONSULTA ---
with aba_consulta:
    st.subheader("Produtos cadastrados")
    produtos = listar_produtos()
    if produtos.empty:
        st.info("Nenhum produto cadastrado.")
    else:
        busca = st.text_input("Buscar por nome, lote ou NCM")
        if busca.strip():
            termo = busca.strip()
            termo_ncm = normalizar_ncm(termo)
            mascara = (
                produtos["nome"].str.contains(termo, case=False, na=False, regex=False)
                | produtos["lote"].fillna("").str.contains(termo, case=False, regex=False)
            )
            if termo_ncm:
                mascara |= produtos["ncm"].fillna("").str.contains(termo_ncm, regex=False)
            produtos = produtos[mascara]

        dias = (pd.to_datetime(produtos["validade"], errors="coerce")
                - pd.Timestamp(date.today())).dt.days
        produtos_display = pd.DataFrame({
            "ID": produtos["id"],
            "Produto": produtos["nome"],
            "Preço (R$)": produtos["preco"],
            "Quantidade": produtos["quantidade"],
            "NCM": produtos["ncm"].map(formatar_ncm),
            "Lote": produtos["lote"].fillna(""),
            "Fabricação": _formatar_datas(produtos["fabricacao"]),
            "Validade": _formatar_datas(produtos["validade"]),
            "Situação": dias.map(rotulo_validade),
        })
        st.dataframe(
            produtos_display,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Preço (R$)": st.column_config.NumberColumn(format="R$ %.2f"),
                "Quantidade": st.column_config.NumberColumn(format="%d")
            }
        )

        st.divider()
        st.subheader("Estoque baixo")
        limite = st.number_input("Considerar estoque baixo quando houver até", min_value=0, value=5, step=1)
        estoque_baixo = produtos_display[produtos_display["Quantidade"] <= limite]
        if estoque_baixo.empty:
            st.success("Nenhum produto abaixo do limite escolhido.")
        else:
            st.warning(f"{len(estoque_baixo)} produto(s) com estoque baixo.")
            st.dataframe(estoque_baixo, use_container_width=True, hide_index=True)

        st.divider()
        st.subheader("Validade")
        alerta = st.number_input("Alertar produtos que vencem em até (dias)", min_value=0, value=30, step=1)
        vencidos = produtos_display[dias < 0]
        a_vencer = produtos_display[(dias >= 0) & (dias <= alerta)]
        if dias.notna().sum() == 0:
            st.info("Nenhum produto com data de validade informada.")
        elif vencidos.empty and a_vencer.empty:
            st.success("Nenhum produto vencido ou próximo do vencimento.")
        else:
            if not vencidos.empty:
                st.error(f"{len(vencidos)} produto(s) vencido(s).")
                st.dataframe(vencidos, use_container_width=True, hide_index=True)
            if not a_vencer.empty:
                st.warning(f"{len(a_vencer)} produto(s) vencendo em até {alerta} dia(s).")
                st.dataframe(a_vencer, use_container_width=True, hide_index=True)

# --- ABA GERENCIAR USUÁRIOS (APENAS ADMIN) ---
if st.session_state.get("perfil") == "admin" and aba_usuarios:
    with aba_usuarios[0]:
        st.subheader("🛡️ Gerenciamento de Usuários e Privilégios")
        st.info("Apenas administradores têm acesso a esta aba.")
        
        tab_criar, tab_gerenciar = st.tabs(["Cadastrar Novo Usuário", "Alterar Privilégios / Excluir"])
        
        with tab_criar:
            with st.form("form_novo_usuario"):
                novo_login = st.text_input("Login do novo usuário")
                nova_senha = st.text_input("Senha inicial", type="password")
                novo_perfil = st.selectbox("Perfil de acesso", ["funcionario", "admin"], index=0)
                btn_criar = st.form_submit_button("Cadastrar Usuário", type="primary")
                
                if btn_criar:
                    if not novo_login.strip() or not nova_senha.strip():
                        st.error("Preencha todos os campos.")
                    else:
                        sucesso, msg = adicionar_usuario(novo_login, nova_senha, novo_perfil)
                        if sucesso:
                            st.success(msg)
                            st.rerun()
                        else:
                            st.error(msg)

        with tab_gerenciar:
            usuarios_df = listar_usuarios()
            if usuarios_df.empty:
                st.warning("Nenhum usuário encontrado.")
            else:
                st.dataframe(usuarios_df, use_container_width=True, hide_index=True)
                
                st.divider()
                st.write("### Modificar Usuário Existente")
                opcoes_usuarios = {
                    f'{row["login"]} (Perfil: {row["perfil"]})': int(row["id"])
                    for _, row in usuarios_df.iterrows()
                }
                usuario_selecionado_nome = st.selectbox("Selecione o usuário", list(opcoes_usuarios.keys()))
                usuario_id = opcoes_usuarios[usuario_selecionado_nome]
                
                col1, col2 = st.columns(2)
                with col1:
                    novo_perfil_select = st.selectbox("Alterar para o perfil", ["admin", "funcionario"], key="alterar_perfil")
                    if st.button("Salvar Alteração de Privilégio", type="secondary"):
                        perfil_atual = usuarios_df[usuarios_df["id"] == usuario_id]["perfil"].iloc[0]
                        if novo_perfil_select != perfil_atual:
                            sucesso, msg = alterar_perfil_usuario(usuario_id, novo_perfil_select)
                            if sucesso:
                                st.success(msg)
                                st.rerun()
                        else:
                            st.info("O usuário já possui este perfil.")

                with col2:
                    st.write(" ") 
                    st.write(" ")
                    if st.button("🗑️ Excluir este Usuário", type="primary"):
                        usuario_logado_id = obter_id_usuario(st.session_state.get("usuario"))
                        
                        sucesso, msg = excluir_usuario(usuario_id, usuario_logado_id)
                        if sucesso:
                            st.success(msg)
                            st.rerun()
                        else:
                            st.error(msg)