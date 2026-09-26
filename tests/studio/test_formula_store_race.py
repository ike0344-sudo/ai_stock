"""수식 저장소도 같은 프로세스의 스레드 여럿이 같은 이름을 동시에 저장·읽어도 죽지 않는다(FastAPI 동기 PUT 은 스레드풀) — test_tmp_file_race 와 같은 시험."""
from studio.infrastructure.formula_store import FileFormulaStore

from .test_tmp_file_race import hammer


def test_formula_put_and_get_same_name_from_many_threads(tmp_path):
    store = FileFormulaStore(tmp_path)
    store.put("동시저장", "C > 1")
    assert hammer(lambda: store.put("동시저장", "C > 2", "설명")) == []
    assert hammer(lambda: (store.put("동시저장", "C > 3"), store.get("동시저장"), store.list())) == []
    got = store.get("동시저장")
    assert got["text"] == "C > 3" and got["created_at"]                    # 덮어써도 만든 시각 유지·내용 온전
    assert not list(tmp_path.glob(".*.tmp"))                                # tmp 잔재 없음
