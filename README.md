# Carteira Bitcoin

Protótipo desktop para Linux com Python e Tkinter. A interface gera e restaura carteiras de teste BIP39 e exibe o primeiro endereço SegWit em regtest.

## Executar

Instale as dependências Python em um ambiente virtual:

```sh
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -r requirements.txt
```

Abra o aplicativo na sessão gráfica:

```sh
python3 app.py
```

A geração, a restauração e a exibição do endereço funcionam sem nó.
Para usar **Verificar nó regtest**, inicie o Bitcoin Core com
`bitcoind -regtest -listen=0 -connect=0`.

## Frase de recuperação

Escolha 12, 15, 18, 21 ou 24 palavras e clique em **Gerar frase de teste**. A frase segue
BIP39, com a lista inglesa, e é gerada localmente. A senha local deriva a chave
com scrypt. O aplicativo salva a frase com AES-256-GCM em
`~/.local/share/bitcoin-carteira/regtest-recovery.json` (ou sob
`XDG_DATA_HOME`, quando definido). **Ver frase salva** reabre o arquivo
com a senha local. A senha do arquivo é independente da frase BIP39.

## Endereço e restauração

**Mostrar endereço de recebimento** desbloqueia o arquivo local e deriva o
primeiro endereço P2WPKH sempre pelo caminho BIP84 `m/84'/1'/0'/0/0`,
com prefixo `bcrt1q`. O protótipo usa a passphrase BIP39 vazia. A senha
local protege o arquivo e pode mudar sem alterar o endereço.

**Restaurar com palavras** aceita uma frase de teste da lista inglesa BIP39,
valida o checksum e salva a frase com uma nova senha local. Use um perfil
de dados vazio para restaurar. Uma frase salva nunca é sobrescrita. Para
experimentar a restauração sem alterar o perfil existente, abra o aplicativo
com um diretório de dados temporário:

```sh
XDG_DATA_HOME="$(mktemp -d)" python3 app.py
```

## Próximas etapas

1. Consultar pagamentos e saldo em regtest para os endereços derivados.
2. Estimar a taxa em sat/vB, preparar a transação e exibir a taxa efetiva
   em sats (soma das entradas menos soma das saídas), junto ao destino,
   valor, troco e total debitado. Transmitir somente após a confirmação
   dessa transação.
