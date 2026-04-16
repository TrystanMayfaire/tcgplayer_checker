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

    # This helps locate the binary on Linux/Streamlit Cloud
    if os.path.exists("/usr/bin/chromium-browser"):
        chrome_options.binary_location = "/usr/bin/chromium-browser"

    try:
        driver = webdriver.Chrome(options=chrome_options)
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
        result_element = WebDriverWait(driver, DYNAMIC_WAIT_TIMEOUT).until(
            EC.presence_of_element_located(DYNAMIC_LOAD_LOCATOR)
        )
        
        poll_start_time = time.time()
        while time.time() - poll_start_time < UPDATE_POLL_TIMEOUT:
            match = re.search(r'\d+', result_element.text)
            if match and int(match.group(0)) > 0:
                return int(match.group(0))
            time.sleep(0.5)
        return 0
    except:
        return -1 # Error state

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
            progress_bar = st.progress(0)
            status_text = st.empty()
            
            for idx, item in enumerate(input_links):
                if item.startswith("Deck:"):
                    current_deck = item.replace("Deck:", "").strip()
                    continue

                # Extract the query, unquote it to remove '+', and clean any extra params
                raw_query = item.split("?q=")[-1]
                clean_card_name = unquote(raw_query).replace('+', ' ').split('&')[0]

                status_text.text(f"Checking: {clean_card_name}...")

                count = perform_search(driver, item, clean_card_name)

                if count > 0:
                    results.append({
                        "Deck": current_deck,
                        "Card": clean_card_name, # This is now the pretty version
                        "Count": count,
                        "URL": item
                    })

                progress_bar.progress((idx + 1) / len(input_links))
                time.sleep(delay)
            
            driver.quit()
            status_text.success("Search Complete!")

            if results:
                st.subheader("Found Cards")
                # Displaying as a clean table is often easier to read than expanders
                st.table(results)

            else:
                st.info("No cards from your list were found in stock.")