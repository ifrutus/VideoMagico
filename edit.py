"""
Versão linha de comando — útil pra processar vários vídeos em lote sem abrir
o navegador.

Exemplo:
    python edit.py --input bruto.mp4 --duration 45 --music music/trilha.mp3
"""
import argparse
import os

from pipeline.pipeline import run_pipeline
from pipeline.youtube import download_youtube, is_youtube_url


def main():
    parser = argparse.ArgumentParser(
        description="Edita automaticamente um vídeo bruto: corta destaques, "
        "gera legendas estilo TikTok e monta com música — tudo local e grátis."
    )
    parser.add_argument("--input", help="Caminho do vídeo bruto")
    parser.add_argument(
        "--youtube", help="Link do YouTube pra baixar e editar, no lugar de --input",
    )
    parser.add_argument("--output-dir", default="output", help="Pasta de saída")
    parser.add_argument("--duration", type=float, default=60.0, help="Duração alvo do vídeo final (segundos)")
    parser.add_argument("--aspect", default="9:16", choices=["9:16", "1:1", "16:9"])
    parser.add_argument("--crossfade", type=float, default=0.4, help="Duração da transição entre clipes (segundos)")
    parser.add_argument("--music", default=None, help="Caminho de uma música de fundo (opcional)")
    parser.add_argument(
        "--model-size", default="base",
        help="Modelo Whisper: tiny, base, small, medium, large-v3 (maior = melhor e mais lento)",
    )
    parser.add_argument("--language", default=None, help="Código do idioma (ex: pt). Vazio = detecção automática")
    args = parser.parse_args()

    if not args.input and not args.youtube:
        parser.error("informe --input (arquivo local) ou --youtube (link)")
    if args.input and args.youtube:
        parser.error("use --input OU --youtube, não os dois")

    def progress_cb(pct, msg):
        print(f"[{pct:5.1f}%] {msg}")

    input_path = args.input
    if args.youtube:
        if not is_youtube_url(args.youtube):
            parser.error(f"isso não parece um link do YouTube válido: {args.youtube}")
        print(f"Baixando do YouTube: {args.youtube}")
        input_path = download_youtube(args.youtube, os.path.join(args.output_dir, "_youtube"), progress_cb=progress_cb)
        print(f"Baixado: {input_path}")

    result = run_pipeline(
        input_path,
        args.output_dir,
        target_duration=args.duration,
        aspect=args.aspect,
        crossfade=args.crossfade,
        music_path=args.music,
        model_size=args.model_size,
        language=args.language,
        progress_cb=progress_cb,
    )

    print("\nPronto! Arquivos gerados:")
    for key in ("final_video", "srt", "transcript", "fcpxml"):
        path = result.get(key)
        if path and os.path.exists(path):
            print(f"  {key}: {path}")
    print(f"\n{result['num_clips']} clipe(s) selecionado(s), {result['total_duration']:.1f}s no total.")


if __name__ == "__main__":
    main()
