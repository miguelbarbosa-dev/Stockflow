import sqlite3
from datetime import datetime
import streamlit as st
import pandas as pd

DB_NAME = "estoque.db"


def conectar():
    return sqlite3.connect(DB_NAME, check_same_thread=False)


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
            return False
        conn.execute("DELETE FROM produtos WHERE id = ?", (int(produto_id),))
        return True


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


st.set_page_config(page_title="Controle de Estoque", page_icon="📦", layout="wide")
criar_tabela()

st.title("📦 Controle de Produtos de Supermercado")
st.caption("Projeto básico em Python, Streamlit e SQLite. Os dados ficam salvos localmente.")

produtos = listar_produtos()
total_produtos = len(produtos)
unidades_estoque = int(produtos["quantidade"].sum()) if not produtos.empty else 0
valor_estoque = float((produtos["preco"] * produtos["quantidade"]).sum()) if not produtos.empty else 0.0

c1, c2, c3 = st.columns(3)
c1.metric("Produtos cadastrados", total_produtos)
c2.metric("Unidades em estoque", unidades_estoque)
c3.metric("Valor estimado do estoque", f"R$ {valor_estoque:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))

aba_produtos, aba_movimentacoes, aba_consulta = st.tabs(
    ["Cadastrar / editar produtos", "Entrada e saída", "Consultar estoque"]
)

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

        if st.button("Excluir produto selecionado", key="excluir_produto"):
            if excluir_produto(produto_id):
                st.success("Produto excluído.")
                st.rerun()
            else:
                st.error("Não é possível excluir: este produto já possui movimentações registradas.")

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

with aba_consulta:
    st.subheader("Produtos cadastrados")
    produtos = listar_produtos()
    if produtos.empty:
        st.info("Nenhum produto cadastrado.")
    else:
        busca = st.text_input("Buscar pelo nome")
        if busca.strip():
            produtos = produtos[produtos["nome"].str.contains(busca.strip(), case=False, na=False)]

        produtos = produtos.rename(columns={
            "id": "ID",
            "nome": "Produto",
            "preco": "Preço (R$)",
            "quantidade": "Quantidade"
        })
        st.dataframe(
            produtos,
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
        estoque_baixo = produtos[produtos["Quantidade"] <= limite]
        if estoque_baixo.empty:
            st.success("Nenhum produto abaixo do limite escolhido.")
        else:
            st.warning(f"{len(estoque_baixo)} produto(s) com estoque baixo.")
            st.dataframe(estoque_baixo, use_container_width=True, hide_index=True)
