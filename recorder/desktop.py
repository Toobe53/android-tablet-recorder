"""Native desktop window (pywebview). Falls back to the browser if unavailable."""
import sys

from . import server as srv


def run(config, log=print, on_handle=None):
    """Open the app in a native window. Returns an error string or None."""
    try:
        import webview
    except Exception as e:  # pywebview missing (e.g. Linux without GTK libs)
        return "pywebview 不可用：%s" % e

    handle = srv.ServerHandle(config, log=log, port=int(config.get("port") or 0)).start()
    if on_handle:
        on_handle(handle)
    width = 1380
    height = 920
    window = webview.create_window(
        "安卓平板录屏助手",
        handle.url,
        width=width,
        height=height,
        min_size=(1040, 700),
        background_color="#0f1115",
        text_select=False,
    )

    def on_closing():
        log("窗口关闭，正在停止任务并退出…")
        handle.stop()
        return True

    try:
        window.events.closing += on_closing
    except Exception:
        pass

    try:
        webview.start(debug=False)
    finally:
        handle.stop()
    return None


def available():
    try:
        import webview  # noqa: F401
        return True
    except Exception:
        return False
