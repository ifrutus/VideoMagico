# Vídeo Mágico 🎬

Joga o vídeo bruto, sai um reel editado do outro lado: corte automático dos
melhores momentos, legenda estilo TikTok, transições e trilha sonora — tudo
rodando **no seu computador**, sem serviço pago, sem "grátis no começo e
depois cobra crédito".

Duas formas de usar, ao mesmo tempo, com um clique só:

- **Arrasta e pronto**: solta o vídeo bruto numa pasta, sai editado sozinho
  do outro lado (heurística automática, sem precisar conversar com nada).
- **Modo chat**: conversa com um diretor de edição por IA (rodando local,
  via Ollama — grátis) pra pedir cortes específicos, zoom, câmera lenta,
  efeitos sonoros e texto de destaque, com ida e volta até ficar do jeito
  que você quer.

Nos dois modos dá pra começar de um **arquivo de vídeo ou de um link do
YouTube** — cola o link, o app baixa sozinho (via
[yt-dlp](https://github.com/yt-dlp/yt-dlp), open-source e gratuito) e edita
normalmente a partir daí.

Tem também um **terceiro modo**: um editor simples pra você mesmo cortar,
reordenar e remover trechos na mão (tipo CapCut/Premiere/DaVinci, só mais
básico) — veja a seção "✂️ Editor simples" mais abaixo.

Também gera um arquivo `.fcpxml` que você importa direto no **Adobe Premiere
Pro**, já com os cortes marcados numa sequência a partir do vídeo bruto
original, pra você dar o acabamento final do seu jeito.

## 🚀 Como abrir

Não precisa saber programar nem instalar Python na mão. É só:

1. **Windows**: dê dois cliques em `Iniciar_Windows.bat`
   **Mac**: dê dois cliques em `Iniciar_Mac.command`
   (no Mac, se aparecer aviso de "desenvolvedor não identificado", clique
   com o botão direito no arquivo → "Abrir" → "Abrir" de novo — só na
   primeira vez)
2. Na primeira vez, uma janela preta (terminal) abre sozinha e configura
   tudo automaticamente — baixa o Python e o FFmpeg (ambos gratuitos) e
   instala as peças do projeto. Leva alguns minutos; das próximas vezes
   abre na hora.
3. O navegador abre sozinho em `http://localhost:8000` com as duas opções:
   - **Modo automático**: arraste o vídeo ali mesmo na página (ou cole um
     link do YouTube no campo logo abaixo), ou solte o arquivo direto na
     pasta `entrada/` (funciona mesmo sem abrir o navegador) — o resultado
     aparece em `saida/`.
   - **Modo chat**: clique em "modo chat" no topo da página, manda o
     vídeo bruto (ou um link do YouTube) e conversa pra pedir a edição.
4. Deixe a janela preta (terminal) aberta enquanto estiver usando.

Nas próximas vezes que abrir, além de pular a configuração inicial, ele
também confere rapidinho se tem alguma peça nova pra instalar (de
atualizações do projeto, tipo essa do YouTube) — só demora de verdade na
primeiríssima vez.

Pra mudar duração alvo, formato (9:16/1:1/16:9), transição, música,
**quantos cortes gerar**, motion graphics, ritmo dos cortes ou estilo da
legenda do **modo automático**, edite o arquivo `config.json` (é só um
arquivo de texto, abre com Bloco de Notas/TextEdit) — não precisa reiniciar
nada.

> **Nota**: esses scripts de instalação automática (`.bat`/`.command`) eu
> não consegui testar num Windows/Mac de verdade (só tenho Linux aqui).
> Testei a fundo tudo o que dava pra testar sem isso — o pipeline completo,
> os efeitos (zoom, câmera lenta, som, texto), e o fluxo de chat de ponta a
> ponta com o Ollama simulado. Se a instalação automática travar em algum
> passo, me manda a mensagem de erro que apareceu na janela que eu ajusto
> rapidinho.

## ▶️ Importando de um link do YouTube

Em vez de arrastar um arquivo, cola o link do vídeo no campo "Cole um link
do YouTube" (funciona com `youtube.com/watch?v=...`, `youtu.be/...` e
`/shorts/...`) e manda ver — o app baixa com o
[yt-dlp](https://github.com/yt-dlp/yt-dlp) (open-source, grátis, sem conta
e sem limite), em até 1080p, e segue pro mesmo corte automático ou chat
normalmente.

> Baixar vídeo do YouTube esbarra nos Termos de Uso deles, então é por sua
> conta: use com vídeos seus ou que você tenha autorização/direito de
> reaproveitar (ex: pra cortar reels a partir de uma live ou vídeo seu que
> já está publicado lá).

Pela linha de comando também dá, no lugar de `--input`:

```bash
python edit.py --youtube "https://www.youtube.com/watch?v=..." --duration 45
```

## ✂️ Vários cortes de uma vez (estilo Opus Clip/Klap)

Em vez de montar UM reel só, o app pode pegar um vídeo bruto (podcast, live,
aula...) e gerar **vários cortes independentes**, cada um já pronto —
legendado, sem os "respiros"/hesitações nas bordas, redimensionado pro
formato escolhido — numa subpasta só dele.

- **Pela interface web**: no campo "Quantos cortes gerar", coloque 1 pra um
  reel só (comportamento de sempre) ou mais de 1 (até 30) pra gerar aquele
  tanto de cortes separados — aí o campo de duração muda pra "duração
  máxima de cada corte".
- **Pela pasta `entrada/`**: ajusta `numero_de_cortes` e
  `duracao_maxima_por_corte_segundos` no `config.json` (o padrão já vem em
  10 cortes de até 60s cada).

Os cortes saem em `saida/<nome do vídeo>/corte_01/`, `corte_02/`... cada um
com seu próprio vídeo final, legenda `.srt`, transcript e `.fcpxml` pro
Premiere. Quando terminam, aparece um aviso do sistema (notificação) dizendo
que os cortes ficaram prontos — no Windows, clicando nele já abre a pasta
direto; em outros sistemas o aviso aparece mas sem o clique (o aviso no
terminal continua aparecendo sempre, de qualquer forma). Na interface web
também aparece um botão **"📂 Ver na pasta"** quando o processamento acaba.

## 🎨 Motion graphics, ritmo dos cortes e estilo da legenda

Três jeitos de deixar o resultado mais "profissional", disponíveis tanto na
interface web (modo automático e modo chat) quanto na pasta `entrada/`
(via `config.json`):

- **Motion graphics (abertura)**: coloque um arquivo de título
  animado/lower third/transição — fundo transparente (.webm VP9+alpha ou
  .mov ProRes 4444) ou fundo verde (chroma key) — na pasta
  `motion_graphics/` (veja `motion_graphics/README.md` pra onde baixar,
  grátis: Mixkit, Pixabay, Videvo). O app detecta sozinho se é alfa ou
  chroma key e sobrepõe automaticamente. No modo automático, escolha pelo
  campo "Motion graphics (abertura)"; no modo chat, só pedir ("bota aquele
  título animado no começo") que o diretor escolhe pelo nome do arquivo.
- **Ritmo dos cortes**: "Rápido" (cortes mais curtos, até 4s — edição mais
  agitada), "Equilibrado" (padrão, sem restrição) ou "Lento" (cortes de
  pelo menos 3.5s — edição mais contemplativa, dá mais tempo pra cada
  momento respirar).
- **Estilo da legenda**: "Padrão", "Impacto" (bem grande e amarela, tipo
  MrBeast), "Minimalista" (discreta, branca, sem negrito) ou "No topo"
  (mesmo estilo padrão, mas a legenda fica em cima em vez de embaixo).

Sem nenhum arquivo em `motion_graphics/`, tudo continua funcionando
normalmente — só não oferece motion graphics nenhum.

## ✂️ Editor simples (cortar, reordenar, remover na mão)

Clique em "✂️ Prefere editar você mesmo?" na página inicial (ou vá direto em
`/editor`) pra abrir um editor bem básico: você manda um vídeo, marca
início e fim de cada pedaço que quer usar, monta a ordem arrastando os
cortes na lista e remove o que não quiser — e exporta um vídeo novo juntando
só esses pedaços, na ordem que você escolheu.

- Marque o início/fim digitando o tempo (em segundos, ex: `12.5`, ou
  minuto:segundo, ex: `1:05`) ou tocando em "usar atual" com o vídeo parado
  no ponto certo.
- Dá pra conferir cada corte com o botão "▶ prévia" antes de exportar.
- Arraste os cortes na lista pra mudar a ordem; o botão "✕ remover" tira um
  corte da lista.
- Não precisa usar os cortes em ordem — pode pegar um pedaço do fim do
  vídeo e colocar primeiro, por exemplo.

É bem mais simples que o modo automático de propósito: sem legenda
queimada, sem redimensionar, sem música — só corta e cola os pedaços que
você escolheu, mantendo o vídeo como ele é. Por enquanto só aceita arquivo
de vídeo (sem link do YouTube nessa tela — use o modo automático ou o chat
pra baixar do YouTube primeiro).

## 💬 Modo chat — conversando com o diretor de IA

O modo chat precisa do [Ollama](https://ollama.com) instalado no seu
computador — é gratuito, roda local, sem conta e sem limite de uso. Sem
ele, o **modo automático continua funcionando normalmente**; só o chat que
fica indisponível (e o app te avisa com uma mensagem clara se isso
acontecer, em vez de travar).

1. Baixe e instale o Ollama: https://ollama.com/download (gratuito)
2. Abra o Ollama uma vez (ele fica rodando em segundo plano)
3. Na primeira vez que você usar o modo chat, o `Iniciar_*` já tenta baixar
   sozinho o modelo padrão (`llama3.2:3b`, ~2GB, leve o suficiente pra
   rodar em CPU comum) — só baixa uma vez, depois fica offline.

No chat, depois de mandar o vídeo bruto, dá pra pedir coisas como:

> "corta os melhores 40 segundos, foca na parte da colheita, bota um zoom
> quando eu falar 'incrível', câmera lenta quando aparecer o abacaxi, e um
> som de whoosh no primeiro corte"

O diretor responde o que fez, o vídeo é renderizado, e você pode pedir
ajustes ("tira a câmera lenta", "corta mais curto") — ele lembra do que já
foi combinado. Cada pedido novo renderiza o vídeo de novo do zero (mais
simples e confiável do que tentar editar só um pedacinho); pra clipes
curtos isso costuma ser rápido.

Efeitos sonoros: coloque arquivos `.mp3`/`.wav` royalty-free (baixados uma
vez, grátis — veja `sfx/README.md`) na pasta `sfx/` pra poder pedir pro
diretor usá-los.

**Modelo maior/melhor**: se seu computador aguentar, troque
`ollama_model` no `config.json` por um modelo maior (ex: `llama3.1:8b`) —
só rodar `ollama pull llama3.1:8b` uma vez e atualizar o `config.json`.

## ✅ Checklist "100% grátis"

Tudo que esse projeto usa é open-source e roda local — nada aqui pede cartão
de crédito, chave de API paga ou tem limite de créditos:

| Etapa | Ferramenta | Licença/custo |
|---|---|---|
| Corte, montagem, legenda queimada, zoom, câmera lenta, música, SFX | FFmpeg | Open-source, grátis, sem limite |
| Transcrição / legendas | faster-whisper (Whisper open-source) | Modelo aberto, baixado uma vez, roda offline |
| Detecção de cena | PySceneDetect | Open-source, grátis |
| Análise de áudio | librosa | Open-source, grátis |
| Diretor de IA do modo chat | Ollama (LLM local, ex: Llama) | Open-source, roda no seu computador, sem API |
| Importar de link do YouTube | yt-dlp | Open-source, grátis, sem conta |
| Interface web | FastAPI (rodando em `localhost`) | Open-source, sem hospedagem paga |
| Aviso do sistema quando os cortes terminam | win10toast-click (Windows) / plyer (demais sistemas) | Open-source, grátis; se não instalar, o app funciona igual, só sem o aviso visual |

A única coisa que **você** precisa providenciar (também de graça) é música
de fundo e/ou efeitos sonoros, se quiser — baixe uma vez de um banco
royalty-free (veja `music/README.md` e `sfx/README.md`) e coloque nas
pastas `music/`/`sfx/`.

## Modo avançado (instalação manual)

Use este caminho se preferir instalar você mesmo (Linux, ou se quiser
rodar com mais controle) em vez de usar os arquivos `Iniciar_*`.

Pré-requisitos: Python 3.10+ e FFmpeg instalados no seu computador.

```bash
# 1. Instale o FFmpeg (se ainda não tiver)
#    macOS:   brew install ffmpeg
#    Windows: choco install ffmpeg   (ou baixe em ffmpeg.org)
#    Linux:   sudo apt install ffmpeg

# 2. Crie um ambiente virtual (recomendado)
python3 -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate

# 3. Instale as dependências (todas open-source, ver requisitos acima)
pip install -r requirements.txt
```

A primeira vez que você processar um vídeo, o `faster-whisper` baixa o
modelo escolhido (ex: "base", ~150MB) do Hugging Face automaticamente — é um
download único e gratuito; depois disso funciona 100% offline.

## Como usar

### Interface web (recomendado)

```bash
python app.py
```

Abre o navegador sozinho em **http://localhost:8000**, com o modo
automático (upload + opções) e um link pro modo chat no topo da página. O
modo automático (arrastar na pasta `entrada/`) roda em segundo plano nesse
mesmo processo.

### Linha de comando (bom pra lote)

```bash
python edit.py --input caminho/do/bruto.mp4 --duration 45 --music music/trilha.mp3
```

Veja todas as opções com `python edit.py --help`.

## Usando o `.fcpxml` no Premiere Pro

1. No Premiere: **File → Import** → escolha o arquivo `destaques_premiere.fcpxml`.
2. Ele traz uma sequência nova já com os trechos selecionados cortados a
   partir do **vídeo bruto original** (não do vídeo já renderizado) — assim
   você pode reajustar cada corte, cor, áudio etc. com liberdade total.
3. Compatibilidade de fcpxml pode variar levemente entre versões do
   Premiere — se algum corte não importar exatamente como esperado, me avise
   que ajusto o formato do XML.

## Como funciona a "mágica"

**Modo automático** (heurística, sem IA de linguagem nenhuma):
1. Extrai o áudio e transcreve com Whisper local (com timestamp por palavra).
2. Detecta cortes de cena (câmera) como sinal extra de "momento".
3. Pontua cada trecho falado pela energia do áudio (fala animada/alto
   volume) + palavras de empolgação ("incrível", "nossa", "olha isso"...) e
   descarta trechos muito curtos (silêncio/hesitação).
4. Seleciona os trechos com maior pontuação até bater a duração alvo, corta,
   redimensiona pro formato escolhido, queima a legenda e monta tudo com
   transições suaves + música de fundo com "duck" automático.

**Modo chat** (o mesmo motor de corte/legenda/música acima, mas quem decide
os trechos e os efeitos é você, via conversa com o Ollama):
1. Transcreve uma vez só, no início da conversa.
2. Cada mensagem sua vira um "plano de edição" em JSON (trechos + efeitos),
   gerado pelo modelo local — com validação defensiva pra descartar qualquer
   timestamp ou nome de arquivo que não faça sentido.
3. Zoom e câmera lenta são aplicados dividindo o clipe em pedaços (o pedaço
   afetado ganha o filtro certo) e remontando; efeitos sonoros entram depois
   da montagem, no instante certo da timeline; texto de destaque usa o mesmo
   sistema de legenda, só que num estilo/posição diferente.
4. Re-renderiza o vídeo inteiro a cada pedido novo (mais simples e confiável
   que tentar editar só um pedaço).

## Ideias pra depois

- Painel de verdade dentro do Premiere (plugin UXP), em vez do import de XML.
- Render incremental no modo chat (só re-renderizar o que mudou entre um
  pedido e outro), se a demora começar a incomodar em vídeos mais longos.
- Empacotar como app instalável, se decidir transformar em produto.
- **"Fase 2" — aprender com vídeo de referência**: hoje, motion
  graphics/ritmo/legenda são escolhas explícitas (você escolhe o preset).
  A ideia pra depois é um passo além: você manda um vídeo de referência que
  gosta (de outro criador, ou um vídeo seu mais antigo que ficou bom), o app
  analisa esse vídeo com um modelo de visão rodando local via Ollama (ex:
  `llava` ou similar) — ritmo de corte, estilo de legenda, uso de motion
  graphics, enquadramento — e vai "aprendendo" um perfil de estilo que entra
  automaticamente nas próximas edições, ficando mais parecido com a
  referência a cada vídeo novo. Depende de você ter o Ollama instalado e
  baixado um modelo com suporte a visão (maior e mais pesado que o
  `llama3.2:3b` usado no modo chat hoje) — ainda não implementado.
