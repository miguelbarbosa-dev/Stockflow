# 📦 StockFlow — Sistema de Gestão de Estoque

## Sobre o Projeto

O StockFlow é um sistema de gerenciamento de estoque desenvolvido em **Python**, utilizando Streamlit e SQLite.

O objetivo é permitir o cadastro e a consulta de produtos, o controle de entradas e saídas de mercadorias e o acompanhamento das quantidades disponíveis em estoque.

O sistema também possui controle de acesso por usuários, com permissões diferentes para administradores e funcionários.

---

## Objetivos

- Desenvolver um sistema simples para gerenciamento de estoque;
- Permitir o cadastro, edição e consulta de produtos;
- Registrar entradas e saídas de mercadorias;
- Acompanhar a quantidade disponível de cada produto;
- Implementar controle de acesso por perfil de usuário;
- Armazenar os dados em um banco de dados SQLite.

---

## Funcionalidades

### 📦 Cadastro e Edição de Produtos

Permite cadastrar e atualizar informações dos produtos, incluindo:

- Nome do produto;
- Preço de compra;
- Margem de lucro;
- Preço de venda;
- Quantidade em estoque;
- NCM;
- Número do lote;
- Data de fabricação;
- Data de validade.

O sistema também impede o cadastro de produtos com nomes duplicados.

### 🔄 Entrada e Saída de Estoque

Permite registrar movimentações de entrada e saída de produtos.

- Entrada: aumenta a quantidade disponível;
- Saída: reduz a quantidade disponível;
- Impede saídas superiores à quantidade disponível;
- Registra a data, o tipo e a quantidade movimentada.

Também disponibiliza um histórico com as últimas 100 movimentações.

### 🔎 Consulta de Estoque

Permite consultar os produtos cadastrados e visualizar suas informações.

Recursos disponíveis:

- Pesquisa por nome, lote ou NCM;
- Visualização dos preços de compra e venda;
- Consulta das quantidades disponíveis;
- Identificação de produtos com estoque baixo;
- Identificação de produtos vencidos;
- Alertas de produtos próximos do vencimento.

### 💰 Cálculo de Preços

O sistema permite informar o preço de compra e a margem de lucro para calcular automaticamente o preço de venda.

Também é possível alterar diretamente o preço de venda, ajustando a margem correspondente.

### 👤 Controle de Usuários

O sistema possui dois perfis de acesso:

**Administrador**
- Cadastrar novos usuários;
- Alterar o perfil de acesso dos usuários;
- Excluir usuários;
- Excluir produtos;
- Acessar as funcionalidades de gerenciamento.

**Funcionário**
- Cadastrar produtos;
- Editar produtos;
- Registrar entradas e saídas;
- Consultar o estoque.

As funcionalidades administrativas ficam restritas ao perfil de administrador.

### 🛡️ Segurança e Backup

- Login com senha armazenada em formato de hash PBKDF2;
- Separação de permissões por perfil;
- Banco de dados SQLite;
- Backup automático diário;
- Manutenção dos últimos 7 backups automáticos;
- Opção de preparar e baixar um backup manualmente.

---

## O que o Projeto Resolve

O StockFlow busca facilitar o controle básico de estoque, centralizando informações que poderiam ser registradas manualmente em planilhas ou anotações.

Com ele, é possível:

- Saber quais produtos estão cadastrados;
- Consultar a quantidade disponível;
- Registrar movimentações de mercadorias;
- Identificar produtos com estoque baixo;
- Acompanhar datas de validade;
- Consultar informações de compra e venda;
- Separar as permissões de administradores e funcionários.

---

## Limitações do Projeto

O StockFlow possui funcionalidades voltadas ao controle básico de estoque, mas não substitui um sistema completo de gestão empresarial (ERP).

Atualmente, o projeto não contempla:

- Controle financeiro e fluxo de caixa;
- Emissão de notas fiscais;
- Integração com sistemas fiscais;
- Controle de vendas e pedidos;
- Integração com fornecedores;
- Gestão de múltiplas lojas ou depósitos;
- Sincronização automática entre diferentes instalações;
- Acesso a informações oficiais de NCM em tempo real.

A validação de NCM utiliza regras básicas de formato. Para consultar descrições e verificar códigos em uma tabela, é necessário disponibilizar um arquivo CSV ou JSON com os dados correspondentes.

---

## Arquivos

```text
StockFlow/
│
├── StockFlow.py       # Aplicação principal
├── estoque.db         # Banco de dados (criado automaticamente)
├── backups/           # Backups automáticos
```

O arquivo `estoque.db` e a pasta `backups/` são gerados automaticamente durante a utilização do sistema.

---

## Tecnologias Utilizadas

- **Python:** linguagem utilizada no desenvolvimento;
- **Streamlit:** criação da interface e interação com o usuário;
- **SQLite:** armazenamento dos dados;
- **Pandas:** organização e consulta dos dados;
- **HTML e CSS:** personalização visual da interface.

---

## Requisitos para Utilização

Para executar o StockFlow, é necessário:

- Computador com Python instalado;
- Navegador de internet atualizado;
- Arquivo principal do projeto (`StockFlow.py`);
- Bibliotecas Streamlit e Pandas instaladas.


### Instalação

**1. Clone o repositório:**

```bash
git clone https://github.com/miguelbarbosa-dev/StockFlow.git
```

**2. Acesse a pasta do projeto:**

```bash
cd StockFlow
```

**3. Instale as dependências:**

```bash
pip install streamlit pandas
```

**4. Execute a aplicação:**

```bash
streamlit run StockFlow.py
```

Após a execução, o Streamlit disponibilizará o endereço local para acessar o sistema pelo navegador.

### Primeiro Acesso

O sistema cria automaticamente um usuário administrador na primeira inicialização do banco de dados.

| Campo | Credencial |
|---|---|
| Login | `admin` |
| Senha | `Estoque@123` |

**Atenção:** essas são as credenciais iniciais definidas no código. O acesso deve ser protegido e a senha padrão não deve ser compartilhada em ambientes de utilização real.

---

## Considerações Finais

O StockFlow foi desenvolvido como um projeto de estudo e prática, envolvendo conceitos de desenvolvimento com Python, manipulação de banco de dados SQLite, autenticação de usuários e criação de interfaces com Streamlit.

Durante o desenvolvimento, foram aplicados conceitos de operações CRUD, validação de dados, controle de permissões, registro de movimentações e organização de informações.

O projeto busca atender às necessidades básicas de controle de estoque, mantendo suas funcionalidades e limitações bem definidas.

## Autor

Desenvolvido por Miguel Barbosa.

Projeto desenvolvido para fins de estudo e prática em desenvolvimento de software.
