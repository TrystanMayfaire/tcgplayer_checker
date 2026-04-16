import time
from urllib.parse import unquote
import os
import sys
import re # Added import for regular expressions
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException
from docx import Document
# from selenium.webdriver.chrome.service import Service # Not needed if chromedriver is in PATH

# --- CONFIGURATION ---
CARD_LIST = r"C:\Users\paulh\Desktop\card_list.docx"
SHOP_NAME = "fourhorsemen"

REQUEST_DELAY_SECONDS = 4
DYNAMIC_WAIT_TIMEOUT = 15 # Wait up to 15 seconds for search results element to appear
UPDATE_POLL_TIMEOUT = 2 # UPDATED: Wait up to 2 extra seconds (down from 5) for JavaScript to update the count
INITIAL_PAGE_LOAD_TIMEOUT = 45 # Increased initial page load timeout to 45s

# --- TCGPLAYER-SPECIFIC LOCATOR (Most Stable) ---
# This waits for the result summary element which confirms the search has finished loading.
DYNAMIC_LOAD_LOCATOR = (By.CSS_SELECTOR, 'div[aria-live="assertive"]')

# --- END CONFIGURATION ---

def get_file_type_by_extension(filepath):
    if filepath.lower().endswith(('.txt', '.csv', '.log')):
        return "text"
    elif filepath.lower().endswith(('.doc', '.docx')):
        return "word_document"
    else:
        return "unknown"

def format_link(card_name, shop_name, links):
    if not card_name or len(card_name) == 0:
        pass
    elif card_name[:5] == "Deck:":
        links.append(card_name)
    else:
        card_name = card_name.replace(' ', '+')
        link = f"https://{shop_name}.tcgplayerpro.com/search/products?q={card_name}"
        links.append(link)
    return links

def create_links(file_path, shop_name):
    if shop_name == "Cardboard Coliseum":
        shop_name = "cardboardscoliseum"
    elif shop_name == "Four Horsemen":
        shop_name = "fourhorsemen"
    elif shop_name == "Four Horsemen Robinson":
        shop_name = "fourhorsemenrobinson"
    elif shop_name == "Keystone":
        shop_name = "keystonegames"

    if not os.path.exists(file_path):
        print(f"ERROR: The file '{file_path}' was not found.")
        return []
    else:
        print(f"Creating links from '{file_path}'...")
        links = []
        file_type = get_file_type_by_extension(file_path)

        if file_type == "word_document":
            file_data = Document(file_path)
            for paragraph in file_data.paragraphs:
                card_name = paragraph.text
                links = format_link(card_name, shop_name, links)
        elif file_type == "text":
            with open(file_path, "r") as file:
                for line in file:
                    card_name = line.strip()
                    links = format_link(card_name, shop_name, links)
        return links

def card_search(i, url, list_len, driver, results):
    # Extract and clean the card name from the URL for easy reading
    try:
        # We try to extract the last 'q=' parameter, which holds the card name
        query_part = unquote(url).split("?q=")[-1]
        card_name = query_part.replace("+", " ").split('&')[0]  # Clean up any remaining URL params
    except IndexError:
        # Handle malformed URL
        card_name = f"MALFORMED URL ({url[:50]}...)"

    print(f"--- Checking {i}/{list_len}: {card_name} ---")

    try:
        # 1. Navigate to the URL (using the page load timeout set in setup)
        driver.get(url)

        # 2. Wait for the dynamic content element to load
        result_element = WebDriverWait(driver, DYNAMIC_WAIT_TIMEOUT).until(
            EC.presence_of_element_located(DYNAMIC_LOAD_LOCATOR)
        )

        # --- POLLING LOOP: Wait for JavaScript to update the '0' count ---
        final_result_count = 0
        poll_start_time = time.time()

        # 3. Enter polling loop to repeatedly check the element's text for a non-zero count
        while time.time() - poll_start_time < UPDATE_POLL_TIMEOUT:
            result_text = result_element.text

            # Extract the numeric count using a regular expression
            match = re.search(r'\d+', result_text)

            if match:
                current_count = int(match.group(0))

                if current_count > 0:
                    # Success: Found a non-zero result, break the poll
                    final_result_count = current_count
                    break

                # If count is 0, keep polling up to the timeout
                final_result_count = 0

            time.sleep(0.5)  # Wait half a second before trying again

        # --- END POLLING LOOP ---

        result_count = final_result_count

        # 4. Report the final count
        if result_count > 0:
            # Success: We found a positive number of results
            results[card_name] = f"✅ AVAILABLE ({result_count} Results Found)"
            print(f"    Result: Successfully extracted count of {result_count}.")
        else:
            pass

    except TimeoutException:
        # This handles both page load and element presence timeouts
        results[card_name] = "FATAL ERROR: Timeout while waiting for page elements"
        print("    Request Failed: Timed out waiting for results or result summary element to load.")

    except WebDriverException as e:
        results[card_name] = f"FATAL ERROR: WebDriver action failed. ({e.__class__.__name__})"
        print(f"    Request Failed (1): {e.__class__.__name__}")

    except Exception as e:
        results[card_name] = f"FATAL ERROR: An unexpected error occurred. ({e.__class__.__name__})"
        print(f"    Request Failed (2): {e.__class__.__name__}")

    return results

def setup_webdriver():
    """Configures and initializes a headless Chrome WebDriver."""
    print("Setting up headless Chrome WebDriver...")
    try:
        chrome_options = Options()
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        # Recommended fix for many timeouts, especially in Linux/VM environments
        chrome_options.add_argument("--disable-gpu")
        
        # Initialize the driver.
        driver = webdriver.Chrome(options=chrome_options)
        
        # Set page load timeout to avoid waiting forever on unresponsive URLs
        driver.set_page_load_timeout(INITIAL_PAGE_LOAD_TIMEOUT)
        
        return driver
    except WebDriverException as e:
        print("\n--- FATAL ERROR: WEBDRIVER SETUP FAILED ---")
        print("Please ensure you have Chrome installed and the correct version of ChromeDriver")
        print("is downloaded and accessible in your system's PATH.")
        print(f"Details: {e}")
        return None


def check_tcgplayer_availability(url_list, decks=False):
    """Checks a list of TCGplayer Pro URLs for non-zero search results using Selenium."""
    
    if not url_list:
        print("No links to check. Exiting.")
        return

    driver = setup_webdriver()
    if driver is None:
        return # Exit if setup failed

    if decks:
        deck_number = len([n for n in url_list if "Deck:" in n])
    else:
        deck_number = 0
        url_list = [n for n in url_list if "Deck:" not in n]

    print(f"\nStarting TCGplayer Pro availability check for {len(url_list) - deck_number} links...")
    print(f"Delaying {REQUEST_DELAY_SECONDS} seconds between site visits.\n")

    results = {}

    num_decks = 0
    deck_names = []
    for i, url in enumerate(url_list, 1):

        if "Deck:" in url:
            print(f"\n{url}")
            deck_names.append(url)
            results[url] = {}
            num_decks += 1
        else:
            i = i - num_decks
            if decks:
                results[deck_names[num_decks-1]] = (
                    card_search(i, url, len(url_list) - deck_number, driver, results[deck_names[num_decks-1]]))
            else:
                results = card_search(i, url, len(url_list) - deck_number, driver, results)

        # Mandatory delay before the next request, even with a browser automation tool
        if i < len(url_list):
            time.sleep(REQUEST_DELAY_SECONDS)

    # Clean up the browser instance
    driver.quit()

    print("\n\n--- FINAL SUMMARY: TCGplayer Availability ---")
    if decks:
        for deck in deck_names:
            print(f"\n{deck}")
            for card, status in results[deck].items():
                print(f"• {card}: {status}")
    else:
        for card, status in results.items():
            print(f"• {card}: {status}")
    print("------------------------------------------")


if __name__ == "__main__":
    if sys.argv[1]:
        CARD_LIST = sys.argv[1]
    else:
        pass

    if sys.argv[2]:
        SHOP_NAME = sys.argv[2]
    else:
        pass

    if sys.argv[3]:
        split_by_deck = True
    else:
        split_by_deck = False

    links = create_links(CARD_LIST, SHOP_NAME)
    check_tcgplayer_availability(links, split_by_deck)
