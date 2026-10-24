from engine import backtest as BT


def test_options_sequential_never_double_count(engine_run):
    for i in engine_run["env"]["items"]:
        o = i["options"]
        cur = o["none"]["monthly_inr_after"]
        for k, v in o.items():
            assert v["monthly_inr_after"] >= 0
            assert v["saving_inr"] <= cur
            assert v["saving_inr"] == cur - v["monthly_inr_after"]


def test_resize_plus_schedule_is_combined(engine_run):
    o = next(i for i in engine_run["env"]["items"] if i["resource"]["name"] == "dev-web-03")["options"]
    assert o["resize+schedule"]["monthly_inr_after"] < min(o["resize"]["monthly_inr_after"], o["schedule"]["monthly_inr_after"])
    additive = o["none"]["monthly_inr_after"] - o["resize"]["saving_inr"] - o["schedule"]["saving_inr"]
    assert o["resize+schedule"]["monthly_inr_after"] > additive          # additive would double count


def test_floor(engine_run):
    floor = engine_run["cfg"]("cost.floor_inr")
    for i in engine_run["env"]["items"]:
        if i["verdict"] == "recommend" and all(a["type"] in ("resize", "schedule", "stop", "snapshot+stop") for a in i["actions"]):
            assert i["options"][i["default_option"]]["saving_inr"] >= floor


def test_total_equals_card_sum(engine_run):
    items = engine_run["env"]["items"]
    total = sum(i["options"][i["default_option"]]["saving_inr"] for i in items if i["verdict"] == "recommend")
    assert total == sum(int(i["options"][i["default_option"]]["saving_inr"]) for i in items if i["verdict"] == "recommend")


def test_headline_saving_band(engine_run):
    items = engine_run["env"]["items"]
    before = sum(i["options"]["none"]["monthly_inr_after"] for i in items)
    saving = sum(i["options"][i["default_option"]]["saving_inr"] for i in items if i["verdict"] == "recommend")
    assert 0.15 <= saving / before <= 0.35


def test_backtest_zero_unsafe(engine_run):
    from engine.run import selection
    bt = BT.run(engine_run["data"], engine_run["cfg"], selection())
    assert bt["unsafe"] == 0, bt["details"]
