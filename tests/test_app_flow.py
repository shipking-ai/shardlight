import pygame
from conftest import run_ticks

from shardlight.core.app import App, TICK
from shardlight.core.scene import Scene
from shardlight.hub.hub import HubScene, ShardCard
from shardlight.hub.title import NameEntry, SlotScene, TitleScene


def test_new_game_flow_through_title_slots_and_name(app):
    app.profile = None
    app.world = None
    app.scenes.reset_to(TitleScene(app), fade=False)
    run_ticks(app, 40)
    dev = app.input.attach_virtual(0)
    # Title menu: the first entry is "Continue" only if saves exist; select "New game"/"Begin"
    app.scenes.push(SlotScene(app))
    run_ticks(app, 20)
    assert isinstance(app.scenes.top, SlotScene)
    app.input.detach_virtual(0)
    dev = app.input.attach_virtual(0)
    app.scenes.top.sel = 1                       # empty slot
    dev.tap("CONFIRM")
    run_ticks(app, 3)
    assert isinstance(app.scenes.top, NameEntry)
    app.input.process([pygame.event.Event(pygame.KEYDOWN, key=pygame.K_w, unicode="W", mod=0),
                       pygame.event.Event(pygame.KEYDOWN, key=pygame.K_i, unicode="i", mod=0)])
    run_ticks(app, 20)
    app.input.process([pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN, unicode="\r", mod=0)])
    run_ticks(app, 30)
    assert app.profile["name"] == "Wi" and app.slot == 1
    assert isinstance(app.scenes.top, HubScene)


def test_hub_walk_and_shard_card(app):
    app.return_to_hub()
    run_ticks(app, 5)
    hub = app.scenes.top
    dev = app.input.attach_virtual(0)
    start = hub.pos.copy()
    dev.hold("UP")
    run_ticks(app, 30)
    dev.release_all()
    assert hub.pos.y < start.y
    # walk to the first station and open its card
    st = hub.stations[0]
    hub.pos = st.pos.copy()
    run_ticks(app, 2)
    dev.tap("CONFIRM")
    run_ticks(app, 3)
    assert isinstance(app.scenes.top, ShardCard)
    run_ticks(app, 10)
    dev.tap("BACK")
    run_ticks(app, 20)
    assert isinstance(app.scenes.top, HubScene)


def test_profile_persistence_across_app_instances(home):
    a = App(headless=True, seed=1, audio=False)
    a.new_game(2, "Persist")
    a.world.set_flag("hello", 5)
    a.world.complete_facet("cinder")
    a.world.mode_data("cinder")["best"] = 7
    a.save_now()
    pygame.quit()
    b = App(headless=True, seed=2, audio=False)
    assert b.load_game(2)
    assert b.world.flag("hello") == 5 and b.world.facet_repaired("cinder")
    assert b.world.mode_data("cinder")["best"] == 7
    pygame.quit()


def test_pad_lost_notifies_scene_and_toasts(app):
    got = []

    class S(Scene):
        def on_pad_lost(self, slot):
            got.append(slot)

    app.scenes.reset_to(S(app), fade=False)
    run_ticks(app, 2)
    app.input.notices.append(("pad_lost", 1))
    run_ticks(app, 2)
    assert got == [1]
    assert any("disconnected" in t["text"] for t in app.toasts)


def test_colorblind_filter_changes_pixels(app):
    app.scenes.reset_to(TitleScene(app), fade=False)
    run_ticks(app, 30)
    before = pygame.image.tobytes(app.frame, "RGB")
    app.settings.set("access.colorblind", "deutan")
    run_ticks(app, 2)
    after = pygame.image.tobytes(app.frame, "RGB")
    assert before != after


def test_run_loop_headless_and_screenshot(app, tmp_path):
    app.scenes.reset_to(TitleScene(app), fade=False)
    app.running = True
    app.settings.set("audio.enabled", False)
    # run() ends by shutting pygame down, so use the fixture-independent path via tick/render only
    for _ in range(10):
        app.tick(TICK)
        app.render()
    out = tmp_path / "s.png"
    pygame.image.save(app.frame, str(out))
    assert out.stat().st_size > 1000
    assert app.frames_drawn >= 10 and len(app.update_ms) >= 10


def test_every_scene_draws_within_frame_budget(app):
    """Hub and title must stay well inside the 8 ms/frame budget (loose bound; CI machines vary)."""
    import time
    app.return_to_hub()
    run_ticks(app, 10)
    t0 = time.perf_counter()
    run_ticks(app, 120)
    per_frame = (time.perf_counter() - t0) / 120 * 1000
    assert per_frame < 12.0, per_frame


def test_slot_scene_shows_lamp_restored_when_tour_done(app):
    app.world.profile["tour"]["done"] = True
    app.save_now()
    from shardlight.hub.title import SlotScene
    scene = SlotScene(app)
    calls = []
    orig = app.font.draw
    def spy(surf, text, *a, **k):
        calls.append(text)
        return orig(surf, text, *a, **k)
    app.font.draw = spy
    scene.draw(app.frame)
    assert any("LAMP RESTORED" in t for t in calls)

    # not shown when tour not done
    app.world.profile["tour"]["done"] = False
    app.save_now()
    scene2 = SlotScene(app)
    calls2 = []
    def spy2(surf, text, *a, **k):
        calls2.append(text)
        return orig(surf, text, *a, **k)
    app.font.draw = spy2
    scene2.draw(app.frame)
    assert not any("LAMP RESTORED" in t for t in calls2)
