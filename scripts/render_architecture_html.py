"""Render the static VISHUE architecture HTML as a PNG with Playwright."""

from __future__ import annotations

from pathlib import Path

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs" / "architecture" / "vishue-architecture.html"
OUTPUT = ROOT / "docs" / "architecture" / "vishue-architecture.png"
CHROME = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")


def main() -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=str(CHROME),
            headless=True,
            args=[
                "--disable-dev-shm-usage",
                "--disable-gpu-sandbox",
                "--use-angle=swiftshader",
                "--disable-features=Vulkan",
            ],
        )
        page = browser.new_page(viewport={"width": 1664, "height": 1200}, device_scale_factor=1)
        page.goto(SOURCE.as_uri(), wait_until="load")
        page.screenshot(path=str(OUTPUT), full_page=True)
        browser.close()
    print(OUTPUT)


if __name__ == "__main__":
    main()
