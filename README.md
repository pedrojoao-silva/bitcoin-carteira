# Carteira Bitcoin

Protótipo desktop para Linux com Python e Tkinter. A interface consulta saldo e gera endereços na rede local de testes do Bitcoin Core.

## Executar

Instale as dependências Python em um ambiente virtual:

```sh
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -r requirements.txt
```

Com Python 3, Tkinter, `bitcoind` e `bitcoin-cli` instalados, inicie o nó:

```sh
bitcoind -regtest -listen=0 -connect=0
```

Em outro terminal, crie a carteira de teste uma vez e abra o aplicativo:

```sh
bitcoin-cli -regtest createwallet carteira-lab
python3 app.py
```

Se a carteira já existir e estiver descarregada, use `bitcoin-cli -regtest loadwallet carteira-lab`. O Bitcoin Core armazena as chaves de teste. O protótipo ainda não inclui histórico nem envio.

## Frase de recuperação

Escolha 12, 15, 18, 21 ou 24 palavras e clique em **Gerar frase de teste**. A frase segue
BIP39, com a lista inglesa, e é gerada localmente. A senha local deriva a chave
com scrypt. O aplicativo salva a frase com AES-256-GCM em
`~/.local/share/bitcoin-carteira/regtest-recovery.json` (ou sob
`XDG_DATA_HOME`, quando definido). **Ver frase salva** reabre o arquivo
com a senha local. A senha do arquivo é independente da frase BIP39.

A frase ainda não controla os endereços e fundos exibidos no protótipo.
O saldo e o endereço de teste continuam vindo da carteira `carteira-lab`
do Bitcoin Core. Use somente em regtest.

## Próximas etapas

1. Derivar as chaves e os endereços da frase e verificar que a restauração
   reproduz os mesmos endereços.
2. Vincular o recebimento e o saldo em regtest aos endereços derivados.
3. Estimar a taxa em sat/vB, preparar a transação e exibir a taxa efetiva
   em sats (soma das entradas menos soma das saídas), junto ao destino,
   valor, troco e total debitado. Transmitir somente após a confirmação
   dessa transação.
