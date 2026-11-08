#!/bin/bash
cd "$(dirname "$0")" || exit 1

RUNTIME="$(pwd)/runtime"
VENV="$RUNTIME/venv"
MARKER="$RUNTIME/.setup_ok"

mkdir -p "$RUNTIME"

pause_and_exit() {
    read -r -p "Pressione ENTER para fechar..." _
    exit 1
}

if [ ! -f "$MARKER" ]; then
    echo "============================================================"
    echo "  Vídeo Mágico - primeira execução, configurando tudo..."
    echo "  Isso só acontece uma vez. Pode levar alguns minutos."
    echo "============================================================"
    echo

    if ! command -v python3 >/dev/null 2>&1; then
        echo "Não encontrei o Python 3 no seu Mac."
        echo "Vou pedir pro macOS instalar as Ferramentas de Linha de Comando"
        echo "(gratuito, oficial da Apple). Uma janela vai aparecer: clique em"
        echo "'Instalar', espere terminar, e depois rode este arquivo de novo."
        xcode-select --install
        pause_and_exit
    fi

    echo "[1/3] Criando ambiente isolado..."
    if ! python3 -m venv "$VENV"; then
        echo "Falhou ao criar o ambiente Python. Copie esta mensagem e me avise."
        pause_and_exit
    fi

    echo "[2/3] Instalando as peças do Vídeo Mágico (open-source, sem custo)..."
    "$VENV/bin/pip" install --upgrade pip -q
    if ! "$VENV/bin/pip" install -q -r requirements.txt; then
        echo "Falhou ao instalar as dependências. Copie a mensagem acima e me avise."
        pause_and_exit
    fi

    echo "[3/3] Verificando o FFmpeg..."
    if ! command -v ffmpeg >/dev/null 2>&1; then
        if command -v brew >/dev/null 2>&1; then
            echo "Instalando o FFmpeg via Homebrew (gratuito)..."
            brew install ffmpeg
        else
            echo "Não encontrei o FFmpeg nem o Homebrew instalados."
            echo "Instale o Homebrew (gratuito, em brew.sh) e depois rode:"
            echo "    brew install ffmpeg"
            echo "Ou me chama que eu te passo um jeito alternativo."
            pause_and_exit
        fi
    fi

    touch "$MARKER"
    echo
    echo "Tudo pronto! Nas próximas vezes isso não roda de novo, abre direto."
    echo
fi

# Garante que peças novas (adicionadas em atualizações do Vídeo Mágico,
# tipo o importador de link do YouTube) fiquem instaladas mesmo em quem já
# configurou tudo antes — rápido quando já está tudo instalado, e se não
# tiver internet no momento só avisa e segue com o que já tem.
echo "Conferindo se há peças novas pra instalar..."
if ! "$VENV/bin/pip" install -q -r requirements.txt; then
    echo "Aviso: não consegui conferir/instalar peças novas agora (sem internet?). Seguindo com o que já está instalado."
fi

# Ollama só é necessário pro MODO CHAT (conversar pedindo zoom, câmera
# lenta, efeitos sonoros). O modo automático (arrastar na pasta entrada)
# funciona sem ele — por isso essa checagem nunca trava a abertura do app.
if ! command -v ollama >/dev/null 2>&1; then
    echo
    echo "Aviso: não encontrei o Ollama instalado."
    echo "Ele só é necessário se você quiser usar o MODO CHAT (conversar"
    echo "pedindo zoom, câmera lenta, efeitos sonoros). O modo automático"
    echo "funciona normalmente sem ele."
    echo "Pra instalar (gratuito): https://ollama.com/download"
    echo
else
    echo "Verificando o modelo de IA do Ollama (só baixa se ainda não tiver)..."
    ollama pull llama3.2:3b >/dev/null 2>&1
fi

echo
echo "Vídeo Mágico rodando! O navegador vai abrir sozinho em alguns segundos."
echo "Pro modo 'arrasta e pronto', solte os vídeos na pasta 'entrada'."
echo "Deixe esta janela aberta enquanto for usar."
echo

"$VENV/bin/python" app.py

read -r -p "Pressione ENTER para fechar..." _
