import pytest
from helpers import make_posting
from pydantic import ValidationError

from jobscout.models import Score


def test_job_id_depends_on_source_and_source_id_only():
    a = make_posting(title="A")
    b = make_posting(title="B")
    assert a.job_id == b.job_id
    assert len(a.job_id) == 16
    assert make_posting(source_id="2").job_id != a.job_id
    assert make_posting(source="lever:x").job_id != a.job_id


def test_content_hash_tracks_title_and_description():
    base = make_posting()
    assert make_posting(description="changed").content_hash != base.content_hash
    assert make_posting(title="changed").content_hash != base.content_hash
    assert make_posting(location="Boston, MA").content_hash == base.content_hash


def test_score_bounds():
    Score(fit=1, timing="unclear", reason="ok")
    with pytest.raises(ValidationError):
        Score(fit=11, timing="unclear", reason="ok")
    with pytest.raises(ValidationError):
        Score(fit=5, timing="someday", reason="ok")
