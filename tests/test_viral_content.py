from pipeline.viral_content import viral_fit, viral_angle


def test_comparison_and_trap_topics_score_high():
    assert viral_fit("SQL GROUP BY vs HAVING: the SQL filter-order trap") >= 62


def test_plain_definition_scores_lower():
    assert viral_fit("Definition and introduction to banking functions") < 62


def test_viral_angle_is_specific():
    assert "trap" in viral_angle("CRR vs SLR: the reserve-location trap").lower()
    assert "head-to-head" in viral_angle("RSA vs AES: why the difference matters").lower()
