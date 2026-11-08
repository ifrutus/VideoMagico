"""
Notificação do sistema operacional quando um lote de cortes termina — um
"textinho" avisando que ficou pronto, com um clique que abre a pasta do
resultado. Só usa bibliotecas open-source/gratuitas que rodam 100% local
(ver README) — nenhuma depende de conta, API paga ou serviço externo.

Isso é só um "plus": se a biblioteca não estiver instalada ou a plataforma
não suportar notificação com clique, a função simplesmente não mostra nada
(NUNCA quebra o resto do app por causa disso) — o aviso de "pronto" sempre
aparece no terminal também, como já acontecia antes.
"""
import os
import platform
import subprocess


def _open_folder(path: str):
    """Abre a pasta no Explorer/Finder/gerenciador de arquivos padrão."""
    try:
        system = platform.system()
        if system == "Windows":
            os.startfile(path)  # type: ignore[attr-defined]
        elif system == "Darwin":
            subprocess.run(["open", path], check=False)
        else:
            subprocess.run(["xdg-open", path], check=False)
    except Exception:
        pass


def notify_done(title: str, message: str, folder_path: str):
    """Mostra uma notificação do sistema (se possível) com um clique que
    abre `folder_path`. Tenta, em ordem:
    1. Windows: win10toast-click (toast nativo com botão/clique real).
    2. Mac: osascript (notificação nativa do Centro de Notificações, sem
       clique pra abrir pasta — limitação da própria API do macOS pra uma
       notificação simples feita por script).
    3. Qualquer plataforma: plyer, se estiver instalado (sem clique).
    Se nada disso funcionar, não faz nada — silenciosamente. Essa função
    nunca levanta exceção pro resto do app."""
    system = platform.system()
    try:
        if system == "Windows":
            try:
                from win10toast_click import ToastNotifier

                ToastNotifier().show_toast(
                    title,
                    message,
                    callback_on_click=lambda: _open_folder(folder_path),
                    duration=10,
                    threaded=True,
                )
                return
            except ImportError:
                pass
        elif system == "Darwin":
            try:
                safe_title = title.replace('"', "'")
                safe_msg = message.replace('"', "'")
                subprocess.run(
                    ["osascript", "-e", f'display notification "{safe_msg}" with title "{safe_title}"'],
                    check=False, timeout=5,
                )
                return
            except Exception:
                pass

        # fallback genérico (Linux, ou Windows sem win10toast-click
        # instalado): sem clique, mas ainda mostra um aviso do sistema.
        try:
            from plyer import notification as plyer_notification

            plyer_notification.notify(title=title, message=message, timeout=10)
        except Exception:
            pass
    except Exception:
        pass
