"""
Modo "arrasta e pronto": fica de olho na pasta entrada/, e assim que você
solta um vídeo bruto lá, processa sozinho e deixa o resultado em saida/.
Não precisa abrir navegador nem digitar comando nenhum depois que o app
tiver aberto.
"""
import json
import os
import shutil
import time
import traceback

from pipeline.pipeline import run_pipeline, run_pipeline_multi
from pipeline.notify import notify_done

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ENTRADA = os.path.join(BASE_DIR, "entrada")
SAIDA = os.path.join(BASE_DIR, "saida")
PROCESSADOS = os.path.join(ENTRADA, "_processados")
ERROS = os.path.join(ENTRADA, "_erros")
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")

VIDEO_EXTS = (".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm")

DEFAULT_CONFIG = {
    "duracao_alvo_segundos": 60,
    "formato": "9:16",
    "transicao_segundos": 0.4,
    "musica": "",
    "qualidade_transcricao": "base",
    "idioma": "pt",
    # Modo "N cortes numa pasta" (como Opus Clip/Klap): em vez de UM reel
    # só, gera até "numero_de_cortes" vídeos SEPARADOS, cada um com até
    # "duracao_maxima_por_corte_segundos", numa subpasta corte_01/,
    # corte_02/... dentro de saida/<nome_do_video>/. Deixe
    # "numero_de_cortes": 1 pra voltar ao modo antigo (um reel só).
    "numero_de_cortes": 10,
    "duracao_maxima_por_corte_segundos": 60,
    # Motion graphics (abertura/título animado): nome de um arquivo dentro
    # da pasta motion_graphics/. Deixe "" pra não usar nenhum.
    "motion_graphic": "",
    # Ritmo dos cortes: "rapido" (cortes curtos, edição mais agitada),
    # "equilibrado" (padrão, sem restrição de duração) ou "lento" (cortes
    # mais longos, edição mais contemplativa).
    "ritmo_cortes": "equilibrado",
    # Estilo visual da legenda: "padrao", "impacto" (bem grande e amarela,
    # tipo MrBeast), "minimalista" (discreta, branca) ou "topo" (igual ao
    # padrão mas no topo do vídeo em vez de embaixo).
    "estilo_legenda": "padrao",
}


def load_config() -> dict:
    config = dict(DEFAULT_CONFIG)
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                config.update(json.load(f))
        except Exception:
            print("Aviso: não consegui ler config.json, usando os valores padrão.")
    return config


def is_stable(path: str, wait: float = 2.0) -> bool:
    """Espera o arquivo parar de crescer, pra não processar um vídeo que
    ainda está sendo copiado/arrastado pra pasta."""
    try:
        size1 = os.path.getsize(path)
        time.sleep(wait)
        size2 = os.path.getsize(path)
        return size1 == size2 and size1 > 0
    except OSError:
        return False


def process_file(path: str, config: dict):
    name = os.path.splitext(os.path.basename(path))[0]
    print(f"\n>>> Novo vídeo detectado: {os.path.basename(path)}")

    out_dir = os.path.join(SAIDA, name)
    music_path = None
    if config.get("musica"):
        candidate = os.path.join(BASE_DIR, "music", config["musica"])
        if os.path.exists(candidate):
            music_path = candidate
        else:
            print(f"  Aviso: música '{config['musica']}' não encontrada em music/, seguindo sem música.")

    motion_graphic_path = None
    if config.get("motion_graphic"):
        candidate_mg = os.path.join(BASE_DIR, "motion_graphics", config["motion_graphic"])
        if os.path.exists(candidate_mg):
            motion_graphic_path = candidate_mg
        else:
            print(f"  Aviso: motion graphic '{config['motion_graphic']}' não encontrado em motion_graphics/, seguindo sem ele.")

    ritmo_cortes = config.get("ritmo_cortes", "equilibrado")
    estilo_legenda = config.get("estilo_legenda", "padrao")

    def progress_cb(pct, msg):
        print(f"  [{pct:5.1f}%] {msg}")

    numero_de_cortes = max(1, int(config.get("numero_de_cortes", 1) or 1))

    try:
        if numero_de_cortes > 1:
            resultado = run_pipeline_multi(
                path,
                out_dir,
                num_cortes=numero_de_cortes,
                duracao_maxima_por_corte=config.get("duracao_maxima_por_corte_segundos", 60),
                aspect=config["formato"],
                crossfade=config["transicao_segundos"],
                music_path=music_path,
                model_size=config["qualidade_transcricao"],
                language=config.get("idioma") or None,
                motion_graphic_path=motion_graphic_path,
                ritmo_cortes=ritmo_cortes,
                estilo_legenda=estilo_legenda,
                progress_cb=progress_cb,
            )
            gerados = resultado["num_cortes_gerados"]
            msg_pronto = (
                f"{gerados} corte(s) prontos, já legendados e sem os respiros/"
                f"hesitações nas bordas."
            )
            print(f">>> Pronto! {msg_pronto} Resultado em: saida/{name}/")
        else:
            run_pipeline(
                path,
                out_dir,
                target_duration=config["duracao_alvo_segundos"],
                aspect=config["formato"],
                crossfade=config["transicao_segundos"],
                music_path=music_path,
                model_size=config["qualidade_transcricao"],
                language=config.get("idioma") or None,
                motion_graphic_path=motion_graphic_path,
                ritmo_cortes=ritmo_cortes,
                estilo_legenda=estilo_legenda,
                progress_cb=progress_cb,
            )
            msg_pronto = "Seu reel está pronto, já legendado e sem os respiros/hesitações nas bordas."
            print(f">>> Pronto! Resultado em: saida/{name}/")

        os.makedirs(PROCESSADOS, exist_ok=True)
        shutil.move(path, os.path.join(PROCESSADOS, os.path.basename(path)))

        notify_done(
            "Vídeo Mágico",
            f'"{os.path.basename(path)}": {msg_pronto} Clique pra abrir a pasta.',
            out_dir,
        )
    except Exception as e:
        # IMPORTANTE: move o vídeo pra fora de entrada/ mesmo quando dá erro.
        # Antes, o arquivo ficava em entrada/ e o laço (a cada poucos
        # segundos) ficava tentando processar ele de novo pra sempre — o
        # mesmo vídeo gerando o mesmo erro em loop infinito, consumindo CPU
        # sem parar. Agora ele vai pra entrada/_erros/ (não mexe no vídeo
        # original) com um arquivo .erro.txt do lado explicando o que
        # aconteceu — dá pra ler isso mesmo sem ver a janela do terminal.
        print(f">>> ERRO ao processar {os.path.basename(path)}: {e}")
        traceback.print_exc()
        os.makedirs(ERROS, exist_ok=True)
        try:
            dest = os.path.join(ERROS, os.path.basename(path))
            shutil.move(path, dest)
            with open(dest + ".erro.txt", "w", encoding="utf-8") as f:
                f.write(f"Erro ao processar este vídeo:\n\n{e}\n\n{traceback.format_exc()}")
            print(f"    Vídeo e detalhes do erro movidos para: entrada/_erros/{os.path.basename(path)}")
        except OSError as move_err:
            print(f"    (não consegui mover o vídeo pra entrada/_erros/: {move_err})")


def watch_loop():
    """O laço que fica de olho na pasta entrada/. Pode ser chamado tanto
    pelo modo standalone (python watcher.py) quanto de dentro do app.py
    (numa thread em segundo plano), pra um único processo cuidar do modo
    'arrasta e pronto' e do modo chat ao mesmo tempo."""
    os.makedirs(ENTRADA, exist_ok=True)
    os.makedirs(SAIDA, exist_ok=True)
    os.makedirs(PROCESSADOS, exist_ok=True)
    os.makedirs(ERROS, exist_ok=True)

    while True:
        config = load_config()
        try:
            for fname in sorted(os.listdir(ENTRADA)):
                fpath = os.path.join(ENTRADA, fname)
                if not os.path.isfile(fpath):
                    continue
                if not fname.lower().endswith(VIDEO_EXTS):
                    continue
                if not is_stable(fpath):
                    continue
                process_file(fpath, config)
        except Exception:
            traceback.print_exc()
        time.sleep(3)


def main():
    os.makedirs(ENTRADA, exist_ok=True)
    os.makedirs(SAIDA, exist_ok=True)
    os.makedirs(PROCESSADOS, exist_ok=True)
    os.makedirs(ERROS, exist_ok=True)

    print("=" * 60)
    print("  Vídeo Mágico rodando!")
    print(f"  Arraste seus vídeos brutos pra pasta: {ENTRADA}")
    print(f"  Os resultados aparecem em: {SAIDA}")
    print("  Deixe esta janela aberta enquanto for usar.")
    print("  Pra mudar duração/formato/música/quantidade de cortes, edite o config.json.")
    print("=" * 60)

    watch_loop()


if __name__ == "__main__":
    main()
