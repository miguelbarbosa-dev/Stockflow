# Controle de Produtos de Supermercado

Projeto básico para cadastro de produtos e controle de estoque usando Python, Streamlit e SQLite.

## Funcionalidades
- Cadastrar, editar, consultar e excluir produtos (produtos com movimentações não podem ser excluídos).
- Registrar entrada e saída de estoque.
- Impedir saídas maiores que o estoque disponível.
- Pesquisar produtos por nome.
- Exibir produtos com estoque baixo.
- Salvar os dados localmente no arquivo `estoque.db`.

## Como executar
1. Instale Python 3.10 ou superior.
2. Abra o terminal nesta pasta.
3. Instale as dependências:

   ```bash
   pip install -r requirements.txt
   ```

4. Inicie o sistema:

   ```bash
   streamlit run app.py
   ```

O navegador abrirá a aplicação. O banco SQLite será criado automaticamente na primeira execução.
