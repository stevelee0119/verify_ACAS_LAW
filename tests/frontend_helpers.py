"""Navigate the workspace through the same project list as a signed-in user."""


def select_first_project(page):
    if not page.locator("#sidebar").is_visible():
        page.get_by_role("button", name="프로젝트 목록", exact=True).click()
    page.locator("#projectList > button").first.click()
