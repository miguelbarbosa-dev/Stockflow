import sqlite3
import hashlib
import hmac
import secrets  
from datetime import datetime

import pandas as pd
import streamlit as st

DB_NAME = "estoque.db"

# Credenciais iniciais e ÚNICAS que nascem como administrador
USUARIO_INICIAL = "admin"
SENHA_INICIAL = "Estoque@123"


def conectar():
    return sqlite3.connect(DB_NAME, check_same_thread=False)


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
        conn.execute("""
            CREATE TABLE IF NOT EXISTS produtos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome TEXT NOT NULL,
                preco REAL NOT NULL CHECK(preco >= 0),
                quantidade INTEGER NOT NULL CHECK(quantidade >= 0),
                criado_em TEXT NOT NULL
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

        # Migração para bancos de dados antigos que não têm a coluna 'perfil'
        try:
            conn.execute("ALTER TABLE usuarios ADD COLUMN perfil TEXT DEFAULT 'funcionario'")
        except sqlite3.OperationalError:
            pass  # Coluna já existe, ignora o erro

        # Cria a conta inicial SOMENTE se ainda não existir nenhum usuário.
        usuario_existente = conn.execute(
            "SELECT id FROM usuarios WHERE login = ?", (USUARIO_INICIAL,)
        ).fetchone()
        if usuario_existente is None:
            salt, senha_hash = gerar_hash_senha(SENHA_INICIAL)
            conn.execute(
                "INSERT INTO usuarios (login, salt, senha_hash, perfil, criado_em) VALUES (?, ?, ?, ?, ?)",
                (
                    USUARIO_INICIAL,
                    salt,
                    senha_hash,
                    'admin',
                    datetime.now().strftime("%d/%m/%Y %H:%M"),
                ),
            )


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


def listar_produtos():
    with conectar() as conn:
        return pd.read_sql_query(
            "SELECT id, nome, preco, quantidade FROM produtos ORDER BY nome",
            conn
        )


def adicionar_produto(nome, preco, quantidade):
    with conectar() as conn:
        conn.execute(
            "INSERT INTO produtos (nome, preco, quantidade, criado_em) VALUES (?, ?, ?, ?)",
            (nome.strip(), float(preco), int(quantidade), datetime.now().strftime("%d/%m/%Y %H:%M"))
        )


def editar_produto(produto_id, nome, preco, quantidade):
    with conectar() as conn:
        conn.execute(
            "UPDATE produtos SET nome = ?, preco = ?, quantidade = ? WHERE id = ?",
            (nome.strip(), float(preco), int(quantidade), int(produto_id))
        )


def excluir_produto(produto_id):
    with conectar() as conn:
        existe_movimentacao = conn.execute(
            "SELECT 1 FROM movimentacoes WHERE produto_id = ? LIMIT 1", (int(produto_id),)
        ).fetchone()
        if existe_movimentacao:
            return False, "Não é possível excluir: este produto já possui movimentações registradas."
        conn.execute("DELETE FROM produtos WHERE id = ?", (int(produto_id),))
        return True, "Produto excluído com sucesso."


def movimentar_estoque(produto_id, tipo, quantidade):
    quantidade = int(quantidade)
    if quantidade <= 0:
        return False, "A quantidade deve ser maior que zero."

    with conectar() as conn:
        produto = conn.execute(
            "SELECT quantidade FROM produtos WHERE id = ?", (int(produto_id),)
        ).fetchone()

        if produto is None:
            return False, "Produto não encontrado."

        estoque_atual = int(produto[0])

        if tipo == "Saída" and quantidade > estoque_atual:
            return False, f"Estoque insuficiente. Disponível: {estoque_atual}."

        if tipo == "Entrada":
            novo_estoque = estoque_atual + quantidade
        else:
            novo_estoque = estoque_atual - quantidade

        conn.execute(
            "UPDATE produtos SET quantidade = ? WHERE id = ?",
            (novo_estoque, int(produto_id))
        )
        conn.execute(
            "INSERT INTO movimentacoes (produto_id, tipo, quantidade, data) VALUES (?, ?, ?, ?)",
            (int(produto_id), tipo, quantidade, datetime.now().strftime("%d/%m/%Y %H:%M"))
        )
    return True, f"{tipo} registrada com sucesso."


# --- Funções de Gerenciamento de Usuários (Apenas Admin) ---

def listar_usuarios():
    with conectar() as conn:
        return pd.read_sql_query(
            "SELECT id, login, perfil, criado_em FROM usuarios ORDER BY id",
            conn
        )

def adicionar_usuario(novo_login, nova_senha, novo_perfil):
    with conectar() as conn:
        try:
            salt, senha_hash = gerar_hash_senha(nova_senha)
            conn.execute(
                "INSERT INTO usuarios (login, salt, senha_hash, perfil, criado_em) VALUES (?, ?, ?, ?, ?)",
                (novo_login.strip(), salt, senha_hash, novo_perfil, datetime.now().strftime("%d/%m/%Y %H:%M"))
            )
            return True, "Usuário cadastrado com sucesso."
        except sqlite3.IntegrityError:
            return False, "Já existe um usuário com este login."

def alterar_perfil_usuario(usuario_id, novo_perfil):
    with conectar() as conn:
        conn.execute(
            "UPDATE usuarios SET perfil = ? WHERE id = ?",
            (novo_perfil, int(usuario_id))
        )
    return True, "Privilégio alterado com sucesso."

def excluir_usuario(usuario_id, usuario_logado_id):
    with conectar() as conn:
        if int(usuario_id) == int(usuario_logado_id):
            return False, "Você não pode excluir sua própria conta."
        
        admins = conn.execute("SELECT id FROM usuarios WHERE perfil = 'admin'").fetchall()
        usuario_alvo = conn.execute("SELECT perfil FROM usuarios WHERE id = ?", (int(usuario_id),)).fetchone()
        
        if usuario_alvo and usuario_alvo[0] == 'admin' and len(admins) <= 1:
            return False, "Não é possível excluir o último administrador do sistema."

        conn.execute("DELETE FROM usuarios WHERE id = ?", (int(usuario_id),))
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
# 1. Nome alterado para StockFlow e emoji da aba removido (usando "SF")
st.set_page_config(page_title="StockFlow", page_icon="SF", layout="wide")

# 2. CSS Personalizado para melhorar o CONTRASTE e a estética
st.markdown("""
    <style>
    /* Título principal com alto contraste e borda inferior */
    .main-title {
        font-size: 2.5rem !important;
        font-weight: 800 !important;
        color: #0F172A !important; /* Azul muito escuro/quase preto */
        border-bottom: 3px solid #2563EB; /* Linha azul vibrante */
        padding-bottom: 0.5rem;
        margin-bottom: 1rem;
    }
    /* Melhora o contraste e destaque dos cards de métrica */
    [data-testid="stMetric"] {
        background-color: #F8FAFC;
        border: 1px solid #E2E8F0;
        border-radius: 8px;
        padding: 15px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.05);
    }
    /* Garante que o texto geral tenha alto contraste (cinza muito escuro) */
    .stApp {
        color: #1E293B;
    }
    /* Destaque para subtítulos */
    .stSubheader {
        color: #334155;
        font-weight: 600;
        margin-top: 1.5rem;
    }
    </style>
""", unsafe_allow_html=True)

criar_tabela()

# Bloqueia todas as funcionalidades até o usuário autenticar.
if not st.session_state.get("autenticado", False):
    tela_login()
    st.stop()

# --- BARRA LATERAL (SIDEBAR) ---
with st.sidebar:
    st.markdown("### StockFlow")
    perfil_display = "Administrador" if st.session_state.get("perfil") == "admin" else "Funcionário"
    st.write(f"👤 Perfil: **{perfil_display}**")
    
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
    with st.form("form_cadastro", clear_on_submit=True):
        nome = st.text_input("Nome do produto")
        col1, col2 = st.columns(2)
        preco = col1.number_input("Preço (R$)", min_value=0.0, value=0.0, step=0.5, format="%.2f")
        quantidade = col2.number_input("Quantidade inicial", min_value=0, value=0, step=1)
        enviado = st.form_submit_button("Cadastrar produto", type="primary")

        if enviado:
            if not nome.strip():
                st.error("Informe o nome do produto.")
            else:
                adicionar_produto(nome, preco, quantidade)
                st.success("Produto cadastrado com sucesso.")
                st.rerun()

    st.divider()
    st.subheader("Editar ou excluir produto")
    produtos = listar_produtos()
    if produtos.empty:
        st.info("Cadastre um produto para poder editá-lo.")
    else:
        opcoes = {
            f'{row["id"]} - {row["nome"]}': int(row["id"])
            for _, row in produtos.iterrows()
        }
        selecionado = st.selectbox("Selecione um produto", list(opcoes.keys()), key="produto_editar")
        produto_id = opcoes[selecionado]
        linha = produtos[produtos["id"] == produto_id].iloc[0]

        with st.form("form_edicao"):
            nome_editado = st.text_input("Nome", value=str(linha["nome"]))
            col1, col2 = st.columns(2)
            preco_editado = col1.number_input(
                "Preço (R$)", min_value=0.0, value=float(linha["preco"]), step=0.5,
                format="%.2f", key=f"preco_{produto_id}"
            )
            quantidade_editada = col2.number_input(
                "Quantidade", min_value=0, value=int(linha["quantidade"]), step=1,
                key=f"quantidade_{produto_id}"
            )
            salvar = st.form_submit_button("Salvar alterações")
            if salvar:
                if not nome_editado.strip():
                    st.error("O nome do produto é obrigatório.")
                else:
                    editar_produto(produto_id, nome_editado, preco_editado, quantidade_editada)
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
        opcoes_mov = {
            f'{row["nome"]} (estoque: {int(row["quantidade"])})': int(row["id"])
            for _, row in produtos.iterrows()
        }
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
    with conectar() as conn:
        historico = pd.read_sql_query("""
            SELECT m.id, p.nome AS produto, m.tipo, m.quantidade, m.data
            FROM movimentacoes m
            JOIN produtos p ON p.id = m.produto_id
            ORDER BY m.id DESC
            LIMIT 100
        """, conn)
    if historico.empty:
        st.info("Nenhuma movimentação registrada.")
    else:
        st.dataframe(historico, use_container_width=True, hide_index=True)

# --- ABA CONSULTA ---
with aba_consulta:
    st.subheader("Produtos cadastrados")
    produtos = listar_produtos()
    if produtos.empty:
        st.info("Nenhum produto cadastrado.")
    else:
        busca = st.text_input("Buscar pelo nome")
        if busca.strip():
            produtos = produtos[produtos["nome"].str.contains(busca.strip(), case=False, na=False)]

        produtos_display = produtos.rename(columns={
            "id": "ID",
            "nome": "Produto",
            "preco": "Preço (R$)",
            "quantidade": "Quantidade"
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
                        usuario_logado_id = conectar().execute(
                            "SELECT id FROM usuarios WHERE login = ?", (st.session_state.get("usuario"),)
                        ).fetchone()[0]
                        
                        sucesso, msg = excluir_usuario(usuario_id, usuario_logado_id)
                        if sucesso:
                            st.success(msg)
                            st.rerun()
                        else:
                            st.error(msg)