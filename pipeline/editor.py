"""
Editor simples (estilo CapCut/Premiere, só que básico): o usuário marca
pedaços do vídeo bruto (início/fim), ordena a lista do jeito que quer e
remove o que não quer — essa função pega essa lista e monta o vídeo final,
cortando cada pedaço e colando na ordem pedida. Sem efeitos, sem legenda,
sem redimensionar: é só "corta aqui, cola ali", igual um editor de verdade.
"""
import os
import shutil
import tempfile

from . import render as R


def export_edit(video_path: str, segments: list[dict], out_path: str, progress_cb=None) -> str:
    """segments: lista ordenada de {"start": segundos, "end": segundos},
    já na ordem final desejada. Cada um pode vir de qualquer parte do vídeo
    bruto, em qualquer ordem (inclusive repetida)."""
    if not segments:
        raise ValueError("Nenhum corte foi marcado — adicione pelo menos um trecho antes de exportar.")

    def report(pct, msg):
        if progress_cb:
            progress_cb(pct, msg)

    tmp_dir = tempfile.mkdtemp(prefix="edit_")
    clip_paths = []
    try:
        total = len(segments)
        for i, seg in enumerate(segments):
            start = float(seg["start"])
            end = float(seg["end"])
            if end <= start:
                raise ValueError(f"Corte {i + 1} inválido: o fim precisa ser depois do início.")
            clip_path = os.path.join(tmp_dir, f"clip_{i:03d}.mp4")
            report(int(10 + 70 * i / total), f"Cortando trecho {i + 1} de {total}...")
            R.cut_raw_segment(video_path, start, end, clip_path)
            clip_paths.append(clip_path)

        report(85, "Juntando os cortes...")
        R.concat_with_crossfade(clip_paths, out_path, crossfade=0.0)
        report(100, "Pronto!")
        return out_path
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
