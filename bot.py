import os
import json
import random
import threading
from io import BytesIO
from flask import Flask
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from telebot.apihelper import ApiTelegramException

# --- FAKE WEB SERVER TO KEEP RENDER HAPPY ---
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is running beautifully on Render!"

# --- CONFIGURATION ---
TOKEN = '8664807029:AAGNevBQxxCt3l1CI-g6QP6LnhKRa3D2_pQ'  # Put your bot token here
CHANNEL_USERNAME = '@deepseek_deepAi' # Must include the @ 
CHANNEL_URL = 'https://t.me/deepseek_deepAi'
DB_FILE = 'database.json'

bot = telebot.TeleBot(TOKEN)

# --- THREAD-SAFE STATE & DATABASE ---
db_lock = threading.Lock()
active_polls = {} # Stores live polls: {chat_id: {data}}
setup_sessions = {} # Stores user setup progress: {user_id: {setup_data}}

def load_db():
    global active_polls
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, 'r') as f:
                loaded = json.load(f)
                # JSON saves keys as strings, we need them as integers for chat_ids
                active_polls = {int(k): v for k, v in loaded.items()}
        except json.JSONDecodeError:
            active_polls = {}

def save_db():
    with open(DB_FILE, 'w') as f:
        json.dump(active_polls, f)

# Load data when bot turns on
load_db()

# --- HELPERS ---

def is_subscribed(user_id):
    """Checks if a user is subscribed to the channel."""
    try:
        status = bot.get_chat_member(CHANNEL_USERNAME, user_id).status
        return status in ['member', 'administrator', 'creator']
    except ApiTelegramException:
        print("WARNING: Bot is not an admin in the channel or channel doesn't exist.")
        return True 

def force_sub_markup():
    """Generates the subscription verification buttons."""
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("📢 Subscribe to Channel", url=CHANNEL_URL))
    markup.add(InlineKeyboardButton("✅ I Have Subscribed", callback_data="check_sub"))
    return markup

def generate_poll_markup(chat_id):
    poll = active_polls[chat_id]
    markup = InlineKeyboardMarkup()
    
    if poll.get('mode') == 'random':
        text = f"🎲 Join Randomly ({len(poll['voted'])}/{poll['total_capacity']})"
        markup.add(InlineKeyboardButton(text, callback_data="vote_random"))
    else:
        for i, group in enumerate(poll['groups']):
            status = "🔴 Full" if len(group['members']) >= group['limit'] else f"🟢 {len(group['members'])}/{group['limit']}"
            text = f"{group['name']} - {status}"
            markup.add(InlineKeyboardButton(text, callback_data=f"vote_{i}"))
            
    return markup

def get_poll_text(chat_id):
    poll = active_polls[chat_id]
    mode_text = "🎲 **Random Assignment Mode**" if poll.get('mode') == 'random' else "🖐 **Manual Selection Mode**"
    
    text = f"📋 **{poll['title']}**\n{mode_text}\n\n"
    text += f"Total Votes: {len(poll['voted'])}/{poll['total_capacity']}\n"
    text += "🔒 *Names are hidden to prevent bias.*\n\n"
    return text

def get_results_text(chat_id):
    poll = active_polls[chat_id]
    text = f"📊 **RESULTS: {poll['title']}**\n"
    text += f"Total Votes: {len(poll['voted'])}/{poll['total_capacity']}\n\n"
    
    for group in poll['groups']:
        text += f"🔹 **{group['name']} ({len(group['members'])}/{group['limit']}):**\n"
        if not group['members']:
            text += " - (No members)\n"
        else:
            for member in group['members']:
                text += f" - {member['display']}\n"
        text += "\n"
    return text

# --- BOT COMMANDS ---

@bot.message_handler(commands=['start'])
def send_welcome(message):
    if not is_subscribed(message.from_user.id):
        bot.send_message(message.chat.id, f"👋 Welcome! Before using this bot, you **MUST** subscribe to our channel.\n\nPlease join {CHANNEL_URL} and click verify.", reply_markup=force_sub_markup())
        return
    
    text = (
        "👋 **Welcome to the Advanced Group Maker Bot!**\n\n"
        "I will help you create unbiased group formations.\n\n"
        "**Available Commands:**\n"
        "🔹 `/create` - Start the step-by-step poll creator\n"
        "🔹 `/view` - (Admin) Secretly view current results\n"
        "🔹 `/end` - (Admin) Close the poll & Export Results\n"
        "🔹 `/cancel` - Cancel a poll or poll creation"
    )
    bot.send_message(message.chat.id, text, parse_mode='Markdown')

@bot.message_handler(commands=['create'])
def start_setup(message):
    user_id = message.from_user.id
    chat_id = message.chat.id

    if not is_subscribed(user_id):
        bot.send_message(chat_id, "⛔️ You must subscribe first!", reply_markup=force_sub_markup())
        return

    if chat_id in active_polls:
        bot.send_message(chat_id, "⚠️ There is already an active poll here. Use `/end` or `/cancel` first.")
        return

    setup_sessions[user_id] = {'chat_id': chat_id, 'step': 'title', 'groups': []}
    msg = bot.send_message(chat_id, "Let's create a poll! 🛠\n\n**Step 1:** What is the Title or Purpose of this poll? (e.g., Robot Project Groups)")
    bot.register_next_step_handler(msg, process_title)

# --- STEP-BY-STEP CREATION LOGIC ---

def process_title(message):
    user_id = message.from_user.id
    if user_id not in setup_sessions or message.text == '/cancel':
        bot.send_message(message.chat.id, "Setup cancelled.")
        return

    setup_sessions[user_id]['title'] = message.text
    
    # Ask for Manual vs Random mode
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("🖐 Users Pick Manually", callback_data="mode_manual"))
    markup.add(InlineKeyboardButton("🎲 Bot Picks Randomly", callback_data="mode_random"))
    bot.send_message(message.chat.id, "**Step 2:** How should users be assigned?", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('mode_'))
def process_mode(call):
    user_id = call.from_user.id
    if user_id not in setup_sessions: return
    
    mode = call.data.split('_')[1] # 'manual' or 'random'
    setup_sessions[user_id]['mode'] = mode
    
    bot.delete_message(call.message.chat.id, call.message.message_id)
    msg = bot.send_message(call.message.chat.id, f"Mode set to: **{mode.upper()}**\n\n**Step 3:** How many groups do you want to create? (Send a number, e.g., 3)", parse_mode='Markdown')
    bot.register_next_step_handler(msg, process_num_groups)

def process_num_groups(message):
    user_id = message.from_user.id
    if message.text == '/cancel': return bot.send_message(message.chat.id, "Setup cancelled.")

    if not message.text.isdigit() or int(message.text) < 1:
        msg = bot.send_message(message.chat.id, "❌ Please send a valid number (e.g., 3). Try again:")
        return bot.register_next_step_handler(msg, process_num_groups)

    setup_sessions[user_id]['num_groups'] = int(message.text)
    setup_sessions[user_id]['current_group'] = 1

    msg = bot.send_message(message.chat.id, f"Great! Now, what is the **Name** for Group 1?")
    bot.register_next_step_handler(msg, process_group_name)

def process_group_name(message):
    user_id = message.from_user.id
    if message.text == '/cancel': return bot.send_message(message.chat.id, "Setup cancelled.")

    setup_sessions[user_id]['temp_name'] = message.text
    
    msg = bot.send_message(message.chat.id, f"What is the **Member Limit** for '{message.text}'? (Send a number)")
    bot.register_next_step_handler(msg, process_group_limit)

def process_group_limit(message):
    user_id = message.from_user.id
    if message.text == '/cancel': return bot.send_message(message.chat.id, "Setup cancelled.")

    if not message.text.isdigit() or int(message.text) < 1:
        msg = bot.send_message(message.chat.id, "❌ Limit must be a number. Try again:")
        return bot.register_next_step_handler(msg, process_group_limit)

    session = setup_sessions[user_id]
    session['groups'].append({
        'name': session['temp_name'],
        'limit': int(message.text),
        'members': []
    })

    if session['current_group'] < session['num_groups']:
        session['current_group'] += 1
        msg = bot.send_message(message.chat.id, f"What is the **Name** for Group {session['current_group']}?")
        bot.register_next_step_handler(msg, process_group_name)
    else:
        # Finish Setup
        chat_id = session['chat_id']
        total_cap = sum(g['limit'] for g in session['groups'])
        
        with db_lock:
            active_polls[chat_id] = {
                'owner': user_id,
                'title': session['title'],
                'mode': session['mode'],
                'groups': session['groups'],
                'voted': {},
                'total_capacity': total_cap,
                'message_id': None
            }
            save_db() # Save to file immediately
        
        del setup_sessions[user_id] # Clean up session
        
        sent_msg = bot.send_message(chat_id, get_poll_text(chat_id), reply_markup=generate_poll_markup(chat_id), parse_mode='Markdown')
        
        with db_lock:
            active_polls[chat_id]['message_id'] = sent_msg.message_id
            save_db()

# --- INLINE BUTTON CALLBACKS ---

@bot.callback_query_handler(func=lambda call: call.data == "check_sub")
def handle_sub_check(call):
    if is_subscribed(call.from_user.id):
        bot.answer_callback_query(call.id, "✅ Verification Successful! You can now use the bot.", show_alert=True)
        bot.delete_message(call.message.chat.id, call.message.message_id)
    else:
        bot.answer_callback_query(call.id, "❌ You have not subscribed yet. Please join the channel first.", show_alert=True)

@bot.callback_query_handler(func=lambda call: call.data.startswith('vote_'))
def handle_vote(call):
    if not is_subscribed(call.from_user.id):
        bot.answer_callback_query(call.id, "⛔️ You must subscribe to our channel to vote!", show_alert=True)
        bot.send_message(call.message.chat.id, f"@{call.from_user.username} Please subscribe to vote:", reply_markup=force_sub_markup())
        return

    chat_id = call.message.chat.id
    user_id = str(call.from_user.id)
    
    # Better Identity System
    username = f" (@{call.from_user.username})" if call.from_user.username else ""
    display_name = f"{call.from_user.first_name}{username}"

    if chat_id not in active_polls:
        return bot.answer_callback_query(call.id, "This poll is inactive.", show_alert=True)

    with db_lock:
        poll = active_polls[chat_id]
        
        # FEATURE: Remove user from old group if they are changing their vote
        if user_id in poll['voted']:
            old_group_idx = poll['voted'][user_id]
            poll['groups'][old_group_idx]['members'] = [m for m in poll['groups'][old_group_idx]['members'] if m['id'] != user_id]

        # FEATURE: Random Assignment vs Manual
        if call.data == "vote_random":
            available = [i for i, g in enumerate(poll['groups']) if len(g['members']) < g['limit']]
            if not available:
                return bot.answer_callback_query(call.id, "All groups are full!", show_alert=True)
            group_index = random.choice(available)
        else:
            group_index = int(call.data.split('_')[1])
            if len(poll['groups'][group_index]['members']) >= poll['groups'][group_index]['limit']:
                return bot.answer_callback_query(call.id, "Group is full! Pick another.", show_alert=True)

        # Register Vote
        poll['voted'][user_id] = group_index
        poll['groups'][group_index]['members'].append({'id': user_id, 'display': display_name})
        save_db()

    bot.answer_callback_query(call.id, f"Success! You joined {poll['groups'][group_index]['name']}.")
    bot.edit_message_text(text=get_poll_text(chat_id), chat_id=chat_id, message_id=poll['message_id'], reply_markup=generate_poll_markup(chat_id), parse_mode='Markdown')

    if len(poll['voted']) >= poll['total_capacity']:
        bot.send_message(chat_id, f"🎉 **Attention:** The poll '{poll['title']}' is now full! The creator can type `/end` to reveal the groups.", parse_mode='Markdown')

# --- POLL MANAGEMENT COMMANDS ---

@bot.message_handler(commands=['view'])
def view_results(message):
    chat_id = message.chat.id
    if chat_id not in active_polls: return bot.send_message(chat_id, "No active poll here.")
    if message.from_user.id != active_polls[chat_id]['owner']: return bot.send_message(chat_id, "⛔️ Only the creator can view results.")

    bot.send_message(chat_id, f"👀 **Current Progress (Poll is still open):**\n\n{get_results_text(chat_id)}", parse_mode='Markdown')

@bot.message_handler(commands=['end'])
def end_poll(message):
    chat_id = message.chat.id
    if chat_id not in active_polls: return bot.send_message(chat_id, "No active poll here.")
    if message.from_user.id != active_polls[chat_id]['owner']: return bot.send_message(chat_id, "⛔️ Only the creator can end the poll.")

    results_text = get_results_text(chat_id)
    bot.send_message(chat_id, f"🛑 **Poll officially closed by creator.** Final Results:\n\n{results_text}", parse_mode='Markdown')
    bot.edit_message_reply_markup(chat_id, active_polls[chat_id]['message_id'], reply_markup=None)
    
    # FEATURE: Export results as a text file
    doc = BytesIO(results_text.replace('*', '').encode('utf-8'))
    doc.name = f"{active_polls[chat_id]['title']}_Results.txt"
    bot.send_document(chat_id, doc, caption="📁 Here is the downloadable text file of the results!")

    with db_lock:
        del active_polls[chat_id]
        save_db()

@bot.message_handler(commands=['cancel'])
def cancel_poll(message):
    chat_id = message.chat.id
    if chat_id in active_polls and message.from_user.id == active_polls[chat_id]['owner']:
        bot.edit_message_reply_markup(chat_id, active_polls[chat_id]['message_id'], reply_markup=None)
        
        with db_lock:
            del active_polls[chat_id]
            save_db()
            
        bot.send_message(chat_id, "🗑 Poll deleted.", parse_mode='Markdown')

# --- FALLBACK / UNDEFINED COMMANDS (ROADMAP) ---

@bot.message_handler(func=lambda message: True)
def undefined_commands(message):
    if message.text.startswith('/'):
        roadmap = (
            "🤖 **Bot Roadmap & Instructions**\n\n"
            "I didn't understand that command. Here is how to use me:\n\n"
            "1️⃣ **Join the Channel:** You must join our channel to use the bot.\n"
            "2️⃣ **Create a Poll:** Type `/create` and I will ask you step-by-step for the Title, Mode, Groups, and Limits.\n"
            "3️⃣ **Monitor:** Type `/view` to secretly check who has joined which group.\n"
            "4️⃣ **Finish:** Type `/end` to lock the poll and show everyone the results.\n\n"
            "Type `/create` to start!"
        )
        bot.send_message(message.chat.id, roadmap, parse_mode='Markdown')

# --- STARTING THE BOT & WEB SERVER (FOR RENDER) ---

def run_bot():
    print("Great Bot System Running...")
    bot.polling(non_stop=True)

if __name__ == "__main__":
    threading.Thread(target=run_bot).start()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
