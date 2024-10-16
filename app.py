import os
from time import sleep
import logging
import csv
import requests
from dotenv import load_dotenv
import mechanize
from bs4 import BeautifulSoup


RETRY_DELAY = 10
RETRY_COUNT = 1


SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))
TICKET_STATUS_FILE_PATH = os.path.join(SCRIPT_DIR, "ticket_status.csv")
LOG_FILE_PATH = os.path.join(SCRIPT_DIR, "log.log")

load_dotenv()

logger = logging.getLogger(__name__)
logging.basicConfig(
    filename=LOG_FILE_PATH, format="%(asctime)s|%(levelname)s|%(filename)s|%(lineno)d|%(message)s", level=logging.INFO
)


def login():
    browser = mechanize.Browser()
    browser.set_handle_equiv(True)
    browser.set_handle_gzip(True)
    browser.set_handle_redirect(True)
    browser.set_handle_referer(True)
    browser.set_handle_robots(False)
    browser.addheaders = [("User-agent", "Firefox")]
    browser.open(os.getenv("HELPDESK_URL_LOGIN"))
    browser.select_form(nr=0)
    browser.form["username"] = os.getenv("HELPDESK_USER")
    browser.form["password"] = os.getenv("HELPDESK_PASS")
    browser.submit()
    return browser


def get_curr_status(browser):
    page_no = 1
    ticket_status_cur = dict()
    while page_no:
        url = os.getenv("HELPDESK_URL_TICKET") + f"/{page_no}"
        browser.open(url)
        html = BeautifulSoup(browser.response().read(), "html.parser")
        tr = html.find("table", {"class": "custom-table"}).find("tbody", {"class": "records-tbody"}).find_all("tr")
        for t in tr:
            td = t.find_all("td")
            if td[0].text == "No Records Found.":
                page_no = -1
                break
            ticket_status_cur[td[0].text] = td[6].text
        page_no += 1
    return ticket_status_cur


def logout(browser):
    browser.open(os.getenv("HELPDESK_URL_LOGOUT"))
    browser.close()


def save_status(status_dict):
    with open(TICKET_STATUS_FILE_PATH, "w") as f:
        w = csv.writer(f, quoting=csv.QUOTE_ALL)
        w.writerows(status_dict.items())


def get_prev_status():
    prev_status = dict()
    if not os.path.exists(TICKET_STATUS_FILE_PATH):
        return prev_status
    with open(TICKET_STATUS_FILE_PATH, "r") as csvfile:
        csv_reader = csv.reader(csvfile)
        for row in csv_reader:
            prev_status[row[0]] = row[1]
    return prev_status


def get_changes(prev_dict, curr_dict):
    message_str = ""
    # Ticket closed
    closed_tick = ""
    for index, prev in enumerate(prev_dict):
        if prev not in curr_dict:
            closed_tick += prev + "\n"
    if closed_tick != "":
        closed_tick = "\nCLOSED:\n" + closed_tick
    # New Ticket created
    new_tick = ""
    for index, curr in enumerate(curr_dict):
        if curr not in prev_dict:
            new_tick += curr + "\n"
    if new_tick != "":
        new_tick = "\nNEW:\n" + new_tick
    # Old ticket updated
    updated_tick = ""
    for index, curr in enumerate(curr_dict):
        if curr in prev_dict:
            if curr_dict[curr] != prev_dict[curr]:
                updated_tick += curr + "\n"
    if updated_tick != "":
        updated_tick = "\nUPDATED:\n" + updated_tick

    message_str += closed_tick + new_tick + updated_tick
    return message_str


def notify(message):
    if not message:
        return False
    bot_token = os.getenv("HELPDESK_TELEGRAM_BOT_TOKEN")
    channel_id = os.getenv("HELPDESK_TELEGRAM_CHANNEL_ID")
    send_msg_url = f"https://api.telegram.org/bot{bot_token}/sendMessage?chat_id={channel_id}&text={message}"
    x = requests.get(send_msg_url)
    return x.json()["ok"] == "True"


if __name__ == "__main__":
    while 1 + RETRY_COUNT:
        try:
            logger.info("Scrapping started.")
            prev_stat = get_prev_status()
            b = login()
            curr_stat = get_curr_status(b)
            changes = get_changes(prev_stat, curr_stat)
            logger.info("Changes: " + changes.replace("\n", " ").replace(":", " - ") if changes else "Changes: None")
            notify(changes)
            save_status(curr_stat)
            logout(b)
            RETRY_COUNT = -1
            logger.info("Scrapping ended.")
        except Exception as e:
            logger.error(e)
            RETRY_COUNT -= 1
            if RETRY_COUNT >= 0:
                logger.info(f"Scrapping failed. Retrying in {RETRY_DELAY} seconds.")
                sleep(RETRY_DELAY)
            else:
                logger.info("Scrapping failed. Will start in next session")
