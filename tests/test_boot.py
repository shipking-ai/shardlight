from conftest import run_ticks


def test_title_and_hub_boot(app):
    from shardlight.hub.title import TitleScene
    app.scenes.reset_to(TitleScene(app), fade=False)
    run_ticks(app, 60)
    app.return_to_hub()
    run_ticks(app, 120)
    assert app.scenes.top.__class__.__name__ == "HubScene"
