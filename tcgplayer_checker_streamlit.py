import streamlit as st
import time
import os
import re
from urllib.parse import unquote
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException
from docx import Document

if "search_results" not in st.session_state:
    st.session_state.search_results = []
if "is_searching" not in st.session_state:
    st.session_state.is_searching = False

# --- CONFIGURATION ---
DYNAMIC_WAIT_TIMEOUT = 15
UPDATE_POLL_TIMEOUT = 2
INITIAL_PAGE_LOAD_TIMEOUT = 45
DYNAMIC_LOAD_LOCATOR = (By.CSS_SELECTOR, 'div[aria-live="assertive"]')

SHOPS = {
    "Four Horsemen": "fourhorsemen",
    "Four Horsemen Robinson": "fourhorsemenrobinson",
    "Cardboard Coliseum": "cardboardscoliseum",
    "Kassar's Games": "kassarsgames",
    "Guy on the Couch Games": "gotc",
    "The Board Room": "theboardroom",
    "Custom...": "custom"
}

def setup_webdriver():
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")

    user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    chrome_options.add_argument(f"user-agent={user_agent}")

    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option('useAutomationExtension', False)

    try:
        driver = webdriver.Chrome(options=chrome_options)
        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
            "source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        })
        driver.set_page_load_timeout(INITIAL_PAGE_LOAD_TIMEOUT)
        return driver
    except Exception as e:
        st.error(f"WebDriver Error: {e}")
        return None

def format_card_link(card_name, shop_handle):
    if not card_name or card_name.startswith("Deck:"):
        return card_name
    query = card_name.strip().replace(' ', '+')
    return f"https://{shop_handle}.tcgplayerpro.com/search/products?q={query}"

def process_input(raw_text, shop_handle, uploaded_file=None):
    links = []
    lines = []
    
    if uploaded_file:
        if uploaded_file.name.endswith('.docx'):
            doc = Document(uploaded_file)
            lines = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
        else:
            lines = [line.decode("utf-8").strip() for line in uploaded_file if line.strip()]
    else:
        lines = [line.strip() for line in raw_text.split('\n') if line.strip()]

    for line in lines:
        links.append(format_card_link(line, shop_handle))
    return links

def perform_search(driver, url, card_name, traget_game_slug=None):
    try:
        driver.get(url)

        # Wait for the body of the page to load
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, 'div.search-results-cards[loading="false"]'))
        )

        # Grab all individual card wrappers inside that container
        card_items = driver.find_elements(By.CLASS_NAME, "search-results-cards__card")

        # If no cards are found, stock is 0
        if not card_items:
            return 0

        match_count = 0
        search_clean = card_name.lower().strip()

        for link in card_items:
            try:
                if target_game_slug:
                    href = link.get_attribute("href")
                    print(f"HREF: {href}")
                    if href:
                        if f"/catalog/{target_game_slug}/" not in href:
                            continue
                name_element = link.find_element(By.CLASS_NAME, "search-results-cards__name")
                title_clean = name_element.text.strip().lower()

                if not title_clean:
                    continue

                if target_game_slug == 'magic':
                    if "art series" in title_clean or "art card" in title_clean:
                        if "art series" not in search_clean and "art card" not in search_clean:
                            continue

                    # Escape any special symbols in the card name (e.g., "Asmoranomardicadaistinaculdacar")
                    escaped_search = re.escape(search_clean)
                    magic_pattern = rf"(?:^|[\-\(\:\s\/\,]){escaped_search}(?:$|[\-\)\:\s\/\,])"

                    if re.search(magic_pattern, title_clean):
                        match_count += 1
                else:
                    sanitized_title = re.sub(r'[^a-z0-9\s]', '', title_clean)
                    sanitized_search = re.sub(r'[^a-z0-9\s]', '', search_clean)
                    if sanitized_search in sanitized_title:
                        match_count += 1
            except Exception as item_error:
                continue

        return match_count

    except TimeoutException:
        st.warning(f"Timeout searching for {card_name}. The site might be slow.")
        return 0
    except Exception as e:
        return 0

# --- UI LAYOUT ---
st.set_page_config(page_title="TCGPlayer Inventory Checker", page_icon="🃏")
st.title("🃏 TCGPlayer Inventory Checker")
st.markdown("#### ⬅️ Select your shop in the sidebar to get started!")
st.caption("You can also adjust the request delay if you encounter timeouts.")

st.divider() # Adds a clean visual break before the input sections

with st.sidebar:
    st.header("Settings")
    shop_choice = st.selectbox("Select Shop", list(SHOPS.keys()))
    if shop_choice == "Custom...":
        shop_handle = st.text_input("Enter Shop Handle (e.g., 'fourhorsemen')")
    else:
        shop_handle = SHOPS[shop_choice]

    game_choice = st.selectbox(
        "Filter by Game",
        ["All Games", "Magic: The Gathering", "Star Wars Unlimited", "Yu-Gi-Oh!", "Disney Lorcana", "Pokémon"]
    )

    # Map human choices to the exact text TCGPlayer uses in their URL href paths
    GAME_MAPPING = {
        "Magic: The Gathering": "magic",
        "Star Wars Unlimited": "star-wars-unlimited",
        "Yu-Gi-Oh!": "yugioh",
        "Disney Lorcana": "lorcana-tcg",
        "Pokémon": "pokemon"
    }
    target_game_slug = GAME_MAPPING.get(game_choice, None)

    delay = st.slider("Request Delay (seconds)", 1, 10, 4)
    st.info("Check 'Decks' mode by including 'Deck: [Name]' in your list.")

tab1, tab2 = st.tabs(["Manual Entry", "File Upload"])

with tab1:
    user_input = st.text_area("Enter card names (one per line):", placeholder="Deck: My Merfolk\nKumena, Tyrant of Orazca\nDeeproot Elite")

with tab2:
    uploaded_file = st.file_uploader("Upload .txt or .docx card list", type=['txt', 'docx'])

if st.button("🔍 Check Availability"):
    input_links = process_input(user_input, shop_handle, uploaded_file)
    
    if not input_links:
        st.warning("Please provide card names or a file.")
    else:
        driver = setup_webdriver()
        if driver:
            results = []
            current_deck_name = "Uncategorized"

            # Calculate total cards (excluding "Deck:" markers) for the counter
            total_cards = len([link for link in input_links if not link.startswith("Deck:")])
            cards_processed = 0

            # Ongoing search information
            status_container = st.status("Searching cards...", expanded=True)
            with status_container:
                deck_display = st.empty()  # Reserved spot for Deck Name
                card_display = st.empty()  # Reserved spot for Card Name

            # Show progress bar
            progress_bar = st.progress(0)

            # Initialize results table
            table_placeholder = st.empty()
            table_config = {
                "URL": st.column_config.LinkColumn(
                    "TCGPlayer Link",
                    display_text="View on TCGPlayer"
                ),
                "Count": st.column_config.NumberColumn("In Stock", format="%d"),
                "Card": st.column_config.TextColumn("Card Name"),
                "Deck": st.column_config.TextColumn("Deck Name")
            }

            for idx, item in enumerate(input_links):
                if item.startswith("Deck:"):
                    current_deck_name = item.replace("Deck:", "").strip()
                    deck_display.markdown(f"📂 **Deck: {current_deck_name}**")
                    continue

                if current_deck_name != "Uncategorized":
                    deck_display.markdown(f"📂 **Deck: {current_deck_name}**")

                # Increment processed count for the counter
                cards_processed += 1

                # Update the status bar label with the (X of Y) counter
                status_container.update(label=f"Searching cards ({cards_processed} of {total_cards})...",
                                        state="running",
                                        expanded=True)
                
                raw_query = item.split("?q=")[-1]
                clean_card_name = unquote(raw_query).replace('+', ' ').split('&')[0]

                card_display.info(f"Searching: **{clean_card_name}**")

                count = perform_search(driver, item, clean_card_name)

                if count > 0:
                    results.append({
                        "Deck": current_deck_name,
                        "Card": clean_card_name,
                        "Count": count,
                        "URL": item
                    })
                    # Update the table placeholder (which is outside the status block)
                    table_placeholder.dataframe(
                        results,
                        column_config=table_config,
                        hide_index=True,
                        use_container_width=True
                    )

                progress_bar.progress((idx + 1) / len(input_links))
                time.sleep(delay)

            # Update the status bar to "Complete" state
            status_container.update(label="Search Complete!", state="complete", expanded=False)
            driver.quit()
            
            if not results:
                st.info("No cards from your list were found in stock.")