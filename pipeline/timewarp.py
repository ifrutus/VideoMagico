"""
Ajuda a dividir um clipe em "pedaços" quando ele tem efeitos de zoom/câmera
lenta em janelas específicas, e a recalcular os tempos das legendas quando
um pedaço muda de duração (câmera lenta/acelerado esticam ou encolhem o
tempo). Zoom não muda duração, só o enquadramento.
"""


def build_pieces(duration: float, effects: list[dict]) -> list[dict]:
    """effects: lista de {"tipo", "inicio", "fim", ...} com tempos relativos
    ao início do segmento (0 = início do clipe), já validados e SEM
    sobreposição entre si. Devolve os pedaços, em ordem, cobrindo
    [0, duration] inteiro — pedaços sem efeito têm effect=None."""
    boundaries = {0.0, duration}
    for e in effects:
        if e["tipo"] in ("zoom", "camera_lenta"):
            boundaries.add(max(0.0, min(duration, e["inicio"])))
            boundaries.add(max(0.0, min(duration, e["fim"])))
    boundaries = sorted(boundaries)

    pieces = []
    for b0, b1 in zip(boundaries, boundaries[1:]):
        if b1 - b0 < 0.02:
            continue
        match = next(
            (
                e for e in effects
                if e["tipo"] in ("zoom", "camera_lenta")
                and abs(e["inicio"] - b0) < 0.05
                and abs(e["fim"] - b1) < 0.05
            ),
            None,
        )
        pieces.append({"start": b0, "end": b1, "effect": match})

    if not pieces:
        pieces = [{"start": 0.0, "end": duration, "effect": None}]
    return pieces


def time_map_from_pieces(pieces: list[dict]):
    """Devolve uma função tempo_original -> tempo_no_clipe_final, levando em
    conta que pedaços de câmera lenta/acelerado esticam ou encolhem o tempo."""
    mapping = []
    cursor = 0.0
    for p in pieces:
        orig_dur = p["end"] - p["start"]
        factor = 1.0
        if p["effect"] and p["effect"]["tipo"] == "camera_lenta":
            factor = 1.0 / p["effect"]["velocidade"]
        new_dur = orig_dur * factor
        mapping.append((p["start"], p["end"], cursor, factor))
        cursor += new_dur

    total_new_duration = cursor

    def remap(t: float) -> float:
        if not mapping:
            return t
        if t <= mapping[0][0]:
            return mapping[0][2]
        for orig_start, orig_end, new_start, factor in mapping:
            if orig_start <= t <= orig_end:
                return new_start + (t - orig_start) * factor
        last = mapping[-1]
        return last[2] + (last[1] - last[0]) * last[3]

    return remap, total_new_duration
