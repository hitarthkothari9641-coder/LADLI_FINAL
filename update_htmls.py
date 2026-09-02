import os
import glob
from bs4 import BeautifulSoup
import re

site_dir = r"c:\Users\hitar\Downloads\Ladli_final\LADLI_visitor-management_fixed\site"

def process_html_files():
    html_files = glob.glob(os.path.join(site_dir, "*.html"))
    for file_path in html_files:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
        
        soup = BeautifulSoup(content, "html.parser")
        
        # 1. Update Header Structure
        header = soup.find("header", class_="site-header")
        if header:
            nav = header.find("nav", class_="nav")
            nav_links_html = "".join([str(c) for c in nav.contents]) if nav else ""
            
            new_header_html = f"""<header class="site-header" role="banner">
  <div class="header-inner">
    <a href="/" class="logo-link" aria-label="LADLI - Home">
      <img src="assets/images/ladli-logo.webp" alt="LADLI Logo" class="logo" width="180" height="auto">
    </a>
    <button class="menu-toggle" aria-expanded="false" aria-controls="main-nav" aria-label="Open navigation menu">
      <span class="hamburger-line"></span>
      <span class="hamburger-line"></span>
      <span class="hamburger-line"></span>
    </button>
    <nav id="main-nav" class="nav-wrap" role="navigation" aria-label="Main navigation">
      {nav_links_html}
    </nav>
  </div>
</header>
<div class="nav-backdrop" aria-hidden="true"></div>
"""
            new_header_soup = BeautifulSoup(new_header_html, "html.parser")
            header.replace_with(new_header_soup)

        # 2. Add loading="lazy" to below-fold images
        for img in soup.find_all("img"):
            src = img.get("src", "").lower()
            if "logo" in src or "hero" in src:
                continue
            if not img.has_attr("loading"):
                img["loading"] = "lazy"

        # 3. Ensure <main> element wrapping content
        if not soup.find("main"):
            body = soup.find("body")
            if body:
                main_tag = soup.new_tag("main")
                
                # We'll collect all elements between header and footer
                nodes_to_wrap = []
                in_main_area = False
                for child in body.children:
                    if child.name == "header":
                        in_main_area = True
                        continue
                    if child.name == "footer":
                        in_main_area = False
                        break
                    if in_main_area and child.name not in ['script', 'style'] and getattr(child, 'get', lambda x: None)('class') != ['nav-backdrop']:
                        nodes_to_wrap.append(child)
                
                if nodes_to_wrap:
                    # Insert main tag after header
                    header_el = soup.find("header")
                    if header_el:
                        header_el.insert_after(main_tag)
                        for node in nodes_to_wrap:
                            main_tag.append(node.extract())

        # Write back the modified HTML
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(str(soup))
        print(f"Updated {os.path.basename(file_path)}")

if __name__ == "__main__":
    process_html_files()
