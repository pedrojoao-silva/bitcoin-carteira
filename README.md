# Carteira Bitcoin

Protótipo desktop para Linux com Python e Tkinter. A interface consulta saldo e gera endereços na rede local de testes do Bitcoin Core.

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
