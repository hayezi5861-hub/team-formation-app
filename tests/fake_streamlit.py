"""테스트 전용 '가짜 Streamlit'.

진짜 Streamlit 없이도 app.py 를 실행해서
  - 어떤 key 의 위젯/영역이 화면에 만들어지는지
  - 버튼을 누르면(= key 로 클릭을 지정하면) 어떤 일이 일어나는지
  - 화면에 어떤 글자가 표시되는지
를 확인할 수 있습니다. 교수님의 자동 채점 프로그램이 key 로 요소를 찾는 방식과 같은 원리입니다.

진짜 Streamlit 처럼 같은 key 를 한 화면에서 두 번 쓰면 오류를 냅니다.
"""
from __future__ import annotations

import types


class RerunSignal(BaseException):
    """st.rerun() 흉내 (진짜 Streamlit 도 BaseException 계열로 처리)"""


class StopSignal(BaseException):
    """st.stop() 흉내"""


class FakeUpload:
    def __init__(self, data: bytes, name: str = "roster.csv"):
        self._data, self.name = data, name

    def getvalue(self) -> bytes:
        return self._data


class Ctx:
    """with st.container(key=...): / with st.columns(2)[0]: 같은 블록."""

    def __init__(self, st, key=None):
        self._st, self._key = st, key

    def __enter__(self):
        self._st._stack.append(self._key)
        return self

    def __exit__(self, *exc):
        self._st._stack.pop()
        return False

    def __getattr__(self, name):          # c1.button(...), c2.write(...) 처럼 열 안에서도 같은 기능을 쓰게 함
        return getattr(self._st, name)


class FakeStreamlit(types.ModuleType):
    def __init__(self):
        super().__init__("streamlit")
        self.session_state = {}
        self.secrets = {}
        self.inputs, self.clicks = {}, set()
        self.keys_ever = set()
        self.reset_run()

    # ---- 실행 관리
    def reset_all(self):
        self.session_state.clear()
        self.inputs.clear()
        self.clicks.clear()
        self.keys_ever = set()
        self.reset_run()

    def reset_run(self):
        self.keys_run = set()
        self.texts = {}
        self.all_texts = []
        self._stack = []

    def text_of(self, key: str) -> str:
        return "\n".join(self.texts.get(key, []))

    # ---- 표시 요소
    def _emit(self, text):
        text = str(text)
        self.all_texts.append(text)
        for k in self._stack:
            if k:
                self.texts.setdefault(k, []).append(text)

    def markdown(self, body, *a, **k): self._emit(body)
    def write(self, *args, **k): self._emit(" ".join(str(x) for x in args))
    def caption(self, body, *a, **k): self._emit(body)
    def title(self, body, *a, **k): self._emit(body)
    def header(self, body, *a, **k): self._emit(body)
    def subheader(self, body, *a, **k): self._emit(body)
    def error(self, body, *a, **k): self._emit("[error] " + str(body))
    def success(self, body, *a, **k): self._emit("[success] " + str(body))
    def info(self, body, *a, **k): self._emit("[info] " + str(body))
    def warning(self, body, *a, **k): self._emit("[warning] " + str(body))
    def metric(self, label, value, *a, **k): self._emit(f"{label}: {value}")
    def dataframe(self, data=None, *a, **k): self._emit(f"<dataframe {len(data or [])} rows>")

    # ---- 블록
    def _register(self, key, kind):
        if key is None:
            return
        if key in self.keys_run:
            raise AssertionError(f"같은 key 를 한 화면에서 두 번 사용했습니다: {key} ({kind})")
        self.keys_run.add(key)
        self.keys_ever.add(key)

    def container(self, *a, key=None, **k):
        self._register(key, "container")
        return Ctx(self, key)

    def expander(self, *a, **k): return Ctx(self)
    def spinner(self, *a, **k): return Ctx(self)

    def columns(self, spec, *a, **k):
        n = spec if isinstance(spec, int) else len(spec)
        return [Ctx(self) for _ in range(n)]

    @property
    def sidebar(self):
        return Ctx(self)

    # ---- 입력 위젯
    def text_input(self, label, value="", *a, key=None, **k):
        self._register(key, "text_input")
        return self.inputs.get(key, value)

    def number_input(self, label, *a, value=0, key=None, **k):
        self._register(key, "number_input")
        return self.inputs.get(key, value)

    def file_uploader(self, label, *a, key=None, **k):
        self._register(key, "file_uploader")
        return self.inputs.get(key)

    def button(self, label, *a, key=None, **k):
        self._register(key, "button")
        return key in self.clicks

    # ---- 흐름 제어 / 기타
    def rerun(self): raise RerunSignal()
    def stop(self): raise StopSignal()
    def set_page_config(self, *a, **k): pass

    def cache_resource(self, *a, **k):
        if len(a) == 1 and callable(a[0]) and not k:
            return a[0]
        return lambda fn: fn
