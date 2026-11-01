# Buscador de imóveis

Coleta anúncios de sites de imobiliárias nas cidades que você escolher, junta tudo numa base local, tira duplicados entre sites, compara o preço por m² com a mediana de imóveis parecidos, aponta preços suspeitos, dá uma nota de 0 a 100 e deixa você comparar os selecionados. Funciona no computador e, pela rede Wi-Fi de casa, no celular.

## Leia antes: o que ele faz e o que não faz

- **Não testei contra sites reais** (meu ambiente não tem internet). A lógica foi testada com páginas simuladas; o primeiro uso em cada site pode pedir ajustes. Nenhum site específico vem pré-configurado.
- Ele tenta ler **dados estruturados** (schema.org, o jeito mais estável) e, se não houver, **detecta cartões de anúncio** (blocos com preço, m² e link). Se mesmo assim falhar, você informa os seletores CSS no `sites.yaml`.
- Sites que montam a página com JavaScript podem exigir `render: true` (precisa de `pip install playwright` e `playwright install chromium`; esse caminho não foi testado).
- Sites com proteção contra robôs podem bloquear. O programa **não tenta burlar** isso: ele se identifica, espera entre os pedidos e obedece o `robots.txt`. Nesses casos, salve a página no navegador (Ctrl+S) e use **Importar**, ou use CSV/JSON.
- Confira os **termos de uso** de cada site antes de coletar; vários proíbem coleta automática. Use por sua conta e para uso pessoal.

## Instalar no computador

Se o comando `buscaimoveis` não for reconhecido no terminal, use `python -m buscaimoveis` no lugar (ex.: `python -m buscaimoveis senha`, `python -m buscaimoveis servir`). Funciona igual.

Precisa do Python 3.10 ou mais novo ([python.org](https://www.python.org/downloads/); no Windows, marque *Add python.exe to PATH*).

- **Windows:** descompacte a pasta e dê dois cliques em `instalar.bat`. Depois, `iniciar.bat`.
- **macOS / Linux:** no terminal, dentro da pasta: `./instalar.sh` e depois `./iniciar.sh`.

O navegador abre em `http://localhost:8000`.

## Versão independente no celular (Termux)

Roda **tudo dentro do celular**: a busca, a base de dados e a interface. Não precisa de computador, servidor nem senha, e a coleta sai pela conexão do seu celular. Você usa o **Termux**, um terminal Android. A instalação baixa o pandas já pronto (do repositório TUR do Termux), sem compilar. A [discussão oficial do Termux](https://github.com/termux/termux-packages/discussions/19126) indica esse caminho e avisa para não instalar o Termux pela Play Store, cuja versão não é a oficial.

1. Instale o **Termux** pelo [F-Droid](https://f-droid.org) ou pelo GitHub oficial do projeto (termux/termux-app), e abra-o.
2. Baixe o `buscador-imoveis.zip` no celular (ele vai para *Downloads*). No Termux:
   ```
   termux-setup-storage              # toque em "Permitir"
   pkg install -y unzip
   cd ~ && unzip ~/storage/downloads/buscador-imoveis.zip && cd buscador-imoveis
   ```
3. Instale (leva alguns minutos e usa a internet):
   ```
   sh termux/instalar-termux.sh
   ```
4. Use:
   ```
   sh termux/iniciar-termux.sh
   ```
   O navegador abre em `http://localhost:8000`. Deixe o Termux aberto (ou em segundo plano) enquanto usa.
5. **Instalar como app:** no Chrome, menu ⋮ → *Instalar app*. O ícone vai para a tela inicial e abre em tela cheia. Com o servidor desligado, o app ainda abre e mostra a última busca salva; para buscar, inicie o servidor.

**Dicas**
- **Não deixar o Android desligar o servidor:** em *Configurações → Apps → Termux → Bateria*, escolha "Sem restrições". O script já liga o *wake lock* do Termux.
- **Iniciar sozinho ao ligar o celular:** instale o app *Termux:Boot*, abra-o uma vez e rode `mkdir -p ~/.termux/boot && cp termux/boot-termux.sh ~/.termux/boot/buscaimoveis && chmod +x ~/.termux/boot/buscaimoveis`.
- **Atualizar:** baixe o zip novo, extraia sobre a pasta e rode `sh termux/instalar-termux.sh` de novo. Seus dados ficam em `~/.buscaimoveis` e não se perdem.
- **Privacidade:** o servidor só aceita conexões do próprio celular. Se quiser pedir senha mesmo assim, rode `buscaimoveis senha`.
- **Sem lxml:** no Termux o programa lê as páginas com o analisador que já vem com o Python (`html.parser`), que é um pouco menos tolerante com HTML quebrado que o lxml usado no computador.

**Não testei no Termux nem num celular, nem as notificações em aparelho real** (o envio foi testado com simulações). A instalação foi escrita a partir da documentação do Termux; o programa e os testes rodaram no computador (com pandas 3.0, a mesma série do Termux) e também com o `html.parser`. Se algum passo do `instalar-termux.sh` falhar, me mande a mensagem de erro.

## Usar no celular (como app)

Neste modo o celular **não roda a busca**: ele abre a interface de um servidor (seu computador ou um servidor na nuvem) e funciona como um app instalado, com ícone na tela inicial, barra de navegação embaixo, filtros em tela cheia, botão de compartilhar anúncio e as últimas buscas salvas para consulta sem internet. Não é um app nativo (APK ou App Store), e a coleta de anúncios só acontece com o servidor ligado.

**Código de acesso.** Sempre que o servidor aceita outros aparelhos (`--celular`, o que `iniciar.bat` e `iniciar.sh` já fazem), ele pede um código. Na primeira vez, a janela do programa mostra um código como `K7M2-9XQP`: anote, porque ele não aparece de novo. O navegador do próprio computador também pede esse código. Para trocar por uma senha sua: `buscaimoveis senha`. Depois de 5 tentativas erradas, o acesso fica bloqueado por 5 minutos. Em **Mais → Sair**, o app apaga os dados salvos no aparelho.

Escolha o jeito de acessar:

| | Funciona fora de casa | Computador precisa ficar ligado | Vira app instalado, com modo offline |
|---|---|---|---|
| **A. Mesmo Wi-Fi** | não | sim | não: só cria um atalho |
| **B. Tailscale (HTTPS privado)** | sim, só nos seus aparelhos | sim | sim |
| **C. Servidor na nuvem** | sim | não | sim |

O navegador só instala o app completo e libera o modo offline em endereços **HTTPS**. Pelo Wi-Fi comum (`http://192.168...`), você tem a interface e um atalho, mas não o modo offline. A aba **Mais** avisa quando o endereço não é HTTPS.

### A. Mesmo Wi-Fi (o mais simples)
1. Deixe computador e celular no mesmo Wi-Fi e rode `iniciar.bat` / `./iniciar.sh`.
2. No celular, abra o endereço mostrado na janela (algo como `http://192.168.0.15:8000`) e digite o código.
3. Menu do navegador → *Adicionar à tela inicial*.

Não use em Wi-Fi público.

### B. De qualquer lugar, sem expor à internet (Tailscale)
O [Tailscale](https://tailscale.com) liga seus aparelhos numa rede privada e fornece HTTPS. Instale-o no computador e no celular, na mesma conta. No computador:

```
buscaimoveis senha
# Windows (cmd):   set BUSCAIMOVEIS_HTTPS=1  &  set BUSCAIMOVEIS_PROXY=1
# macOS / Linux:   export BUSCAIMOVEIS_HTTPS=1 BUSCAIMOVEIS_PROXY=1
buscaimoveis servir
tailscale serve --bg --https=8000 localhost:8000
```
O último comando mostra o endereço `https://...ts.net` para abrir no celular (a [documentação do comando](https://tailscale.com/docs/reference/tailscale-cli/serve) tem os detalhes; se ele pedir, ative o HTTPS nas configurações da sua conta Tailscale). Para desligar: `tailscale serve --https=8000 off`. O computador precisa ficar ligado e com o programa aberto.

### C. Servidor na nuvem (computador desligado)
O pacote inclui `Dockerfile` e `docker-compose.yml`. Num serviço que rode Docker com **disco persistente** (para a base de dados em `/dados`) e HTTPS:
1. Defina a senha em `BUSCAIMOVEIS_SENHA` (8+ caracteres) e, por estar atrás de HTTPS, `BUSCAIMOVEIS_HTTPS=1` e `BUSCAIMOVEIS_PROXY=1`.
2. Use **uma única instância** do programa (as tarefas em andamento ficam na memória dele).
3. Abra o endereço HTTPS do serviço no celular e instale o app.

Limitações: não testei o contêiner nem nenhum serviço de nuvem. Alguns sites de imobiliária bloqueiam acessos vindos de servidores de nuvem, e a coleta na nuvem é a que mais depende de ajuste. Como o programa passa a ficar na internet, use uma senha forte e mantenha as dependências atualizadas.

### Instalar o app no celular
- **Android (Chrome):** abra o endereço HTTPS, aba **Mais → Instalar app** (ou menu ⋮ → *Instalar app*).
- **iPhone (Safari):** botão Compartilhar → *Adicionar à Tela de Início*.

### O que funciona sem internet
O app abre e mostra a **última busca** e as últimas listas de imobiliárias vistas naquele aparelho, com um aviso no topo. Coletar, mapear, importar e atualizar exigem conexão com o servidor.

### Segurança
- Com senha, nada da interface abre sem login; o login usa cookie assinado, e pedidos vindos de outros sites são recusados.
- Nas funções de imobiliárias da interface (descobrir, mapear e consultar), o programa **não visita endereços da rede interna** (como `192.168.x.x` ou serviços internos da nuvem), para impedir que um site mal-intencionado o use para atacar sua rede. A coleta pelo `sites.yaml` usa só os endereços que você mesmo escreveu no arquivo.
- Sem `BUSCAIMOVEIS_HTTPS=1` em acesso por HTTPS, o cookie não recebe a marca *Secure*; com a variável ligada em endereço `http://`, o login não funciona.
- Para abrir só no próprio computador, sem senha: `buscaimoveis servir` (sem `--celular`).

## Buscas salvas e alertas (automático)

Salve uma busca e o programa a executa sozinho, de tempos em tempos, e avisa quando aparece um imóvel **novo** que atende aos filtros ou quando o preço de um já visto **cai** (por padrão, queda de 3% ou mais).

- **Criar:** na aba **Alertas**, ajuste os filtros, abra *Salvar os filtros atuais como busca*, dê um nome e a cidade (`Curitiba/PR`). Ou, pela linha de comando: `buscaimoveis salvar-busca "Apto Batel" --cidade "Curitiba/PR" --tipos apartamento --quartos 2 --pmax 700000`. Limite de 20 buscas.
- **A primeira execução só registra o que já existe** (não manda 300 avisos de uma vez). Depois, só chegam as novidades. Se uma execução não conseguir ler nenhum anúncio, ela não conta como primeira: a base de comparação só é criada quando houve dados.
- **Quem executa:** `buscaimoveis servir` já liga o agendador (desligue com `--sem-vigia`). Sem interface, use `buscaimoveis vigiar` (deixe aberto) ou `buscaimoveis vigiar --uma-vez` num agendador (cron). Para rodar uma agora: `buscaimoveis executar-busca ID`. Ver os avisos: `buscaimoveis alertas`.
- **Educação com os sites:** o intervalo mínimo entre execuções de uma mesma busca é de **30 minutos** (padrão 120, em `alertas.intervalo_min` do `sites.yaml`), e só uma coleta roda por vez. Não adianta, nem é gentil, consultar de minuto em minuto.
- **Horário de silêncio:** `alertas.silencio: "22:00-07:00"` guarda os avisos e envia depois. Eles continuam aparecendo na aba Alertas.

### Notificações no celular

Configure em `alertas.notificar` do `sites.yaml` (`buscaimoveis config` mostra onde está) e teste com `buscaimoveis testar-alerta` (ou o botão na aba Alertas):

| Canal | Como ligar |
|---|---|
| `termux` | No Termux: `pkg install termux-api` **e** instale o app *Termux:API* (F-Droid), dando permissão de notificações. Aparece como notificação do Android; tocar abre o anúncio. |
| `ntfy` | Instale o app *ntfy*, assine um tópico e ponha o mesmo nome em `alertas.ntfy.topico`. `buscaimoveis topico` gera um nome aleatório. **O nome do tópico é a "senha"**: quem o souber lê seus avisos, então não o divulgue. Os avisos passam pelo servidor `ntfy.sh` (ou o seu, em `alertas.ntfy.servidor`). |
| `telegram` | Crie um bot com o BotFather; ponha `token` e `chat_id` em `alertas.telegram` (use `${NOME}` e guarde o valor com `buscaimoveis chave NOME`). |

Se nenhum canal estiver configurado, os alertas aparecem só na aba Alertas. Se um envio falhar, o programa tenta de novo (até 5 vezes).

**No celular, o Android pode pausar o Termux.** Para as buscas rodarem com a tela apagada: Termux em *Bateria → Sem restrições*; o `iniciar-termux.sh` já liga o *wake lock*; e para subir ao ligar o celular, use o Termux:Boot (o `boot-termux.sh` roda o servidor com o agendador).

## APIs de anúncios (opcional)

Pesquisei o que existe para conectar:

- **Portais grandes (ZAP, Viva Real, OLX, QuintoAndar):** não têm API pública para quem só quer buscar imóveis. O uso é bloqueado por termos de uso; o programa não tenta contornar.
- **Sistemas usados pelas imobiliárias (Vista/Loft, Jetimob, ImobiBrasil e similares):** a API existe, mas é fechada para o cliente da imobiliária; terceiros não conseguem chave. Não dá para usar como comprador.
- **GeckoAPI:** o único serviço de terceiros que achei com cadastro aberto (tem créditos de teste, depois é **pago**). O `sites.yaml` traz um exemplo (`geckoapi-zap`, `ativo: false`) que **não foi testado**: os nomes dos campos vieram da documentação deles e podem precisar de ajuste. Confira o preço e os termos de uso do serviço antes de ligar.

O conector genérico fica na seção `apis:` do `sites.yaml`: você descreve a URL, os parâmetros (`{cidade}`, `{pmax}`, `{quartos_lista}`...), onde está a lista de resultados e o mapa de campos, sem programar. Regras de segurança: só roda com `ativo: true`; há limite diário de chamadas (`limite_diario`, padrão 30) porque cada chamada pode custar; a chave nunca vai escrita no arquivo: use `${GECKOAPI_CHAVE}` e guarde o valor com `buscaimoveis chave GECKOAPI_CHAVE` (digitado sem aparecer na tela; fica em `~/.buscaimoveis/chaves.json`, legível só por você). `buscaimoveis apis` mostra o uso do dia e se falta chave. Mensagens de erro nunca incluem a chave nem o endereço completo.

## Descobrir as imobiliárias da cidade e consultar cada uma

Na aba **Imobiliárias** (ou pela linha de comando) o fluxo é:

1. **Descobrir:** o programa procura as imobiliárias da cidade no OpenStreetMap (grátis, mas a cobertura varia: só aparecem as que alguém cadastrou lá). Com uma chave de API do Google Places na variável `GOOGLE_PLACES_KEY` (ou `--google-chave`), ele também usa o Google, que acha mais, mas **é cobrado pelo Google**. Redes sociais e portais agregadores são descartados. O que faltar, você cadastra à mão.
2. **Mapear:** para cada imobiliária marcada, o programa abre a página inicial, procura o **formulário de busca** (finalidade, tipo, cidade, bairro, preço, quartos...) ou, se não houver, os **links de listagem** de venda e aluguel, e confirma que consegue ler anúncios de verdade antes de dar o site como pronto.
3. **Consultar:** preenche o formulário de cada site com os seus filtros, percorre as páginas de resultado e grava os anúncios. Os filtros também são aplicados depois, localmente, então o resultado respeita tudo o que você marcou mesmo que o site ignore algum campo.

Cada site termina com um estado: busca encontrada, busca achada mas anúncios não lidos, sem busca encontrada ou sem site. Sites montados por JavaScript costumam cair em "anúncios não lidos"; para eles use **Importar** ou configure o site à mão no `sites.yaml`.

```
buscaimoveis explorar --cidade "Curitiba/PR" --finalidade venda --tipos apartamento --quartos 2 --pmax 700000
buscaimoveis descobrir "Curitiba/PR"          # só descobre
buscaimoveis imobiliarias                      # estado de cada uma
buscaimoveis adicionar-site "Alfa" alfa.com.br "Curitiba/PR"
buscaimoveis mapear --cidade Curitiba
buscaimoveis consultar --cidade "Curitiba/PR" --finalidade aluguel --tipos casa
```
O programa usa poucas requisições por site (1 a 3 para mapear, até `--paginas` para consultar), espera entre elas e obedece o `robots.txt`.

## Configurar os sites (modo manual)

```
buscaimoveis config        # mostra onde está o sites.yaml
buscaimoveis testar-url "https://site.com.br/venda/apartamentos/curitiba-pr?pagina=1"
```
Copie o bloco `exemplo-imobiliaria`, ajuste a `url` (marcadores: `{finalidade} {tipo} {cidade} {uf} {pagina}`), troque `ativo` para `true`. Use `testar-url` com uma página de resultados real para ver quantos anúncios são lidos.

## Usar

Pela interface: abas **Coletar** (cidades como `Curitiba/PR`), **Importar**, **Resultados** (filtros e nota) e **Selecionados** (comparação lado a lado).

Pela linha de comando:
```
buscaimoveis buscar --cidades "Curitiba/PR" "Florianópolis/SC" --finalidade venda --tipos apartamento casa
buscaimoveis importar anuncios.csv --cidade "Curitiba/PR"
buscaimoveis listar --cidades Curitiba --tipos apartamento --quartos 2 --pmax 700000 \
    --obrigatorias varanda --desejaveis piscina elevador --sem-suspeitos --csv resultado.csv
```

## Como a nota funciona

0 a 100, combinando (com pesos que você ajusta): preço por m² frente à mediana de imóveis do mesmo tipo, finalidade e cidade; quantas características desejáveis o imóvel tem; e se o bairro está na sua lista de preferidos. Anúncios com preço por m² muito fora do padrão são marcados como suspeitos. Mudanças de preço ao longo do tempo ficam registradas.

## Dados e testes

Tudo fica em `~/.buscaimoveis` (base `imoveis.db` e `sites.yaml`). Para testar: `python -m unittest discover -s tests` (se o Node.js estiver instalado, inclui também o teste da interface).
