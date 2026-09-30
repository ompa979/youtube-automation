import pipeline.quality as quality


def test_max_words_is_80():
    assert quality.MAX_WORDS == 80


def test_never_is_not_globally_banned():
    class S:
        title = "TCP handshake explained"
        hook = "Why does TCP need an ACK?"
        description = ""
        pinned_comment = "Which part was clearest?"
        scenes = []
    # Technical use of “never” should not fail the generic sensational regex.
    assert not quality.SENSATIONAL_UNVERIFIED.search("TCP never sends data before the handshake completes")


def test_real_hype_is_still_banned():
    assert quality.SENSATIONAL_UNVERIFIED.search("90% of students get this wrong")
    assert quality.SENSATIONAL_UNVERIFIED.search("secret that guarantees success")
