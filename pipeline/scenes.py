"""
Detecção de troca de cena com PySceneDetect (open-source). Usado como sinal
extra pra identificar "momentos" no vídeo bruto (cortes de câmera, mudanças
de plano, etc.) — sem nenhum serviço externo.
"""
from scenedetect import open_video, SceneManager
from scenedetect.detectors import ContentDetector


def detect_scenes(video_path: str, threshold: float = 27.0) -> list[tuple[float, float]]:
    """Devolve lista de (inicio_seg, fim_seg) de cada cena detectada.

    Se o vídeo não tiver cortes de câmera nítidos (ex: um plano único), a
    lista terá só uma cena cobrindo o vídeo inteiro — e o pipeline segue
    normalmente usando só a energia de áudio pra achar destaques.
    """
    video = open_video(video_path)
    scene_manager = SceneManager()
    scene_manager.add_detector(ContentDetector(threshold=threshold))
    scene_manager.detect_scenes(video)
    scene_list = scene_manager.get_scene_list()

    if not scene_list:
        duration = video.duration.get_seconds()
        return [(0.0, duration)]

    return [(start.get_seconds(), end.get_seconds()) for start, end in scene_list]
