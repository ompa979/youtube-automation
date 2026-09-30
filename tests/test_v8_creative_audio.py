from pathlib import Path
import sys, types
try:
    import google.generativeai  # type: ignore
except Exception:
    google_mod=types.ModuleType("google"); genai_mod=types.ModuleType("google.generativeai"); setattr(google_mod,"generativeai",genai_mod); sys.modules.setdefault("google",google_mod); sys.modules.setdefault("google.generativeai",genai_mod)
from types import SimpleNamespace
from unittest.mock import patch
import tempfile
from PIL import Image
import pipeline.script_gen as sg
import pipeline.engagement_v2 as ev2
from pipeline.topic_engine import score_topic

def _script():
    roles=["hook","context","mechanism","example","exam_takeaway","difference_card"]
    texts=["M3 is broader than M1 because term deposits are included.","M1 focuses on the most liquid forms of money used for payments.","Start with M1, then add the relevant term deposits to form M3.","If demand deposits are 100 and term deposits are 300, M3 includes both parts.","When a question mentions term deposits, think about the broader money aggregate.","M1 is narrower, while M3 becomes broader by adding term deposits."]
    scenes=[]
    for i,(r,t) in enumerate(zip(roles,texts)):
        scenes.append(SimpleNamespace(index=i,narration=t,tts_text=t,image_prompt="premium concept visual",on_screen_text=r,card_points=[r],action_type=r,action_payload="",motion_type="",camera_motion="",sfx_cue=""))
    return SimpleNamespace(title="M1 vs M3",hook=texts[0],description="Learn M1 and M3.",tags=["m1","m3"],pinned_comment="What next?",thumbnail_text="M1 VS M3",thumbnail_subline="KEY DIFFERENCE",thumbnail_visual_prompt="",scenes=scenes)

def test_difference_role():
    s=_script(); sg._v6_enforce_contract(s); assert [x.action_type for x in s.scenes]==["hook","context","mechanism","example","exam_takeaway","difference_card"]

def test_difference_not_game():
    s=_script(); sg._v6_enforce_contract(s); assert "A OR B" not in s.scenes[-1].action_payload.upper(); assert s.scenes[-1].on_screen_text=="KEY DIFFERENCE"

def test_thumbnail_1280x720():
    with tempfile.TemporaryDirectory() as td:
        root=Path(td); bp=root/"bg.jpg"; Image.new("RGB",(1280,720),(60,80,110)).save(bp); out=root/"thumb.jpg"
        with patch.object(ev2,"_request_ai_background",return_value=None):
            ev2.create_custom_thumbnail(root/"video.mp4",out,0.5,"M1 VS M3","RBI GRADE B",background_path=bp,topic="M1 vs M3",variants=3,subline="TERM DEPOSITS")
        assert Image.open(out).size==(1280,720)

def test_thumbnail_layout_prompt():
    p=ev2._v8_thumbnail_visual_prompt("CRR vs SLR","CRR OR SLR?","WHICH USES CASH?","hero_right_text_left")
    assert "RIGHT 58 percent" in p and "Landscape 16:9" in p and "NO WORDS" in p.upper()

def test_topic_score_100scale():
    s=score_topic("CRR vs SLR: where each reserve is kept","banking_awareness",trend=75,query_signal=4); assert 0<=s.trend_score<=100 and 0<=s.seo_score<=100
