"""Build the daily Misago shop free-reward flow from captured UI samples."""

import json
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
IMAGE = ROOT / "resource/image"
PIPELINE = ROOT / "resource/pipeline/shop.json"
SAMPLES = ROOT / "resource/navigation/samples"


def crop(source, box, name):
    image = cv2.imdecode(np.fromfile(SAMPLES / source, dtype=np.uint8), cv2.IMREAD_COLOR)
    assert image is not None, source
    x1, y1, x2, y2 = box
    fragment = image[y1:y2, x1:x2]
    fragment = cv2.resize(fragment, None, fx=0.8, fy=0.8, interpolation=cv2.INTER_AREA)
    cv2.imencode(".png", fragment)[1].tofile(IMAGE / name)


def match(name, roi, threshold=0.8):
    return {"recognition": "TemplateMatch", "template": name, "roi": roi,
            "threshold": threshold, "method": 10001}


def click(box, next_nodes, message):
    return {"action": "Click", "target": box, "post_delay": 1400,
            "next": next_nodes, "focus": {"Node.Action.Succeeded": message}}


def main():
    # Samples are 1600x900, while MaaFramework normalizes the frame to 1280x720.
    # Save only cropped UI fragments; the source screenshots and their UID stay local.
    crop("shop_limited.png", (120, 25, 305, 67), "shop_title.png")
    crop("shop_limited.png", (790, 100, 1035, 151), "shop_limited_title.png")
    crop("shop_limited.png", (1340, 265, 1410, 295), "shop_claim.png")
    crop("shop_featured.png", (385, 751, 454, 782), "shop_free.png")
    crop("shop_featured.png", (85, 318, 199, 351), "shop_featured_tab.png")
    crop("shop_free_dialog.png", (714, 231, 889, 281), "shop_reward_title.png")

    nodes = {
        "Shop_Start": {"recognition": "DirectHit", "action": "DoNothing", "next": ["Shop_RewardStart", "Shop_Page", "Shop_FromHome"], "timeout": 20000},
        "Shop_RewardStart": {**match("shop_reward_title.png", [550, 175, 175, 80]),
                             **click([1000, 450, 150, 85], ["Shop_Page"], "关闭已领取奖励弹窗。")},
        "Shop_FromHome": {**match("nav_home_misago_shop.png", [1037, 541, 200, 108]),
                          **click([1100, 565, 100, 65], ["Shop_Page"], "已进入弥萨格商店。"), "timeout": 20000},
        "Shop_Page": {**match("shop_title.png", [90, 15, 165, 48]), "action": "DoNothing",
                      "next": ["Shop_OpenFeatured"], "timeout": 15000},
        # 2026-10 改版：左侧页签变为 月相观测 / 精选礼盒 / 幻衣订购 / 课题礼匣 / 银芯购买 / 兑换商店。
        # 原来的「限时礼盒两笔领取」已下线，唯一的日常免费奖励在【精选礼盒】→【每日常规补助】的【免费】。
        "Shop_OpenFeatured": {**match("shop_title.png", [90, 15, 165, 48]),
                              **click([62, 180, 120, 48], ["Shop_FeaturedFree", "Shop_Exit"], "查看精选礼盒的每日免费补助。")},
        "Shop_FeaturedFree": {"recognition": "And", "all_of": [match("shop_featured_tab.png", [55, 175, 125, 55]),
                              match("shop_free.png", [300, 590, 80, 45])], "box_index": 1,
                               **click([315, 592, 72, 40], ["Shop_RewardFeatured", "Shop_Exit"], "领取精选礼盒每日免费补助。")},
        "Shop_RewardFeatured": {**match("shop_reward_title.png", [550, 175, 175, 80]),
                                **click([1000, 450, 150, 85], ["Shop_Exit"], "关闭每日免费补助弹窗。")},
        "Shop_Exit": {**match("shop_title.png", [90, 15, 165, 48]),
                      **click([1210, 8, 65, 66], [], "免费商店奖励已检查完，返回主界面。")},
    }
    PIPELINE.write_bytes((json.dumps(nodes, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    interface_path = ROOT / "interface.json"
    interface = json.loads(interface_path.read_text(encoding="utf-8-sig"))
    interface["task"] = [task for task in interface["task"] if task["name"] != "商店免费奖励"]
    insert_at = next(i for i, task in enumerate(interface["task"]) if task["name"] == "信箱全部领取")
    interface["task"].insert(insert_at, {
        "name": "商店免费奖励", "label": "弥萨格商店：领取红点免费奖励", "entry": "Shop_Start",
        "option": [], "default_check": False, "repeatable": False,
        "description": "日常流程：从主界面或商店页打开【精选礼盒】，领取【每日常规补助】的【免费】奖励；只点击免费按钮，不购买标价礼盒。",
    })
    interface_path.write_bytes((json.dumps(interface, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


if __name__ == "__main__":
    main()
