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

def perform_search(driver, url, card_name):
    try:
        driver.get(url)

        # Wait for the body of the page to load
        WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.TAG_NAME, "body")))

        # Wait for the live region to be present
        result_element = WebDriverWait(driver, DYNAMIC_WAIT_TIMEOUT).until(
            EC.presence_of_element_located(DYNAMIC_LOAD_LOCATOR)
        )

        # Poll until the text actually contains a number
        # Look for "results" or "result" in the text to confirm it's loaded
        poll_start_time = time.time()
        while time.time() - poll_start_time < UPDATE_POLL_TIMEOUT:
            current_text = result_element.text.lower()

            # Check if the text has updated from empty/loading to a result count
            if "result" in current_text:
                match = re.search(r'\d+', current_text)
                if match:
                    return int(match.group(0))

            time.sleep(0.5)

        # If we exit the loop without finding "result", it's likely truly 0
        return 0
    except TimeoutException:
        st.warning(f"Timeout searching for {card_name}. The site might be slow.")
        return -1
    except Exception as e:
        return -1

# --- UI LAYOUT ---
st.set_page_config(page_title="TCGPlayer Inventory Checker", page_icon="🃏")
st.title("🃏 TCGPlayer Inventory Checker")

with st.sidebar:
    st.header("Settings")
    shop_choice = st.selectbox("Select Shop", list(SHOPS.keys()))
    if shop_choice == "Custom...":
        shop_handle = st.text_input("Enter Shop Handle (e.g., 'fourhorsemen')")
    else:
        shop_handle = SHOPS[shop_choice]
    
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
            current_deck = "Uncategorized"

            # Inform user search is starting
            status_container = st.status("Searching cards...", expanded=True)

            # Show progress bar
            progress_bar = st.progress(0)

            # Initialize results table
            table_placeholder = st.empty()

            for idx, item in enumerate(input_links):
                if item.startswith("Deck:"):
                    current_deck = item.replace("Deck:", "").strip()
                    status_container.write(f"📂 **Deck: {current_deck}**")
                    continue

                raw_query = item.split("?q=")[-1]
                clean_card_name = unquote(raw_query).replace('+', ' ').split('&')[0]

                status_container.write(f"Checking: {clean_card_name}...")

                count = perform_search(driver, item, clean_card_name)

                if count > 0:
                    results.append({
                        "Deck": current_deck,
                        "Card": clean_card_name,
                        "Count": count,
                        "URL": item
                    })
                    # Update the table placeholder (which is outside the status block)
                    table_placeholder.dataframe(results, use_container_width=True)

                progress_bar.progress((idx + 1) / len(input_links))
                time.sleep(delay)

            # Update the status bar to "Complete" state
            status_container.update(label="Search Complete!", state="complete", expanded=False)
            driver.quit()

            # Final persistence check
            if results:
                table_placeholder.dataframe(results, use_container_width=True)
            else:
                st.info("No cards from your list were found in stock.")