import os
import json
import time
import uuid
import random
import threading
from io import BytesIO
from flask import Flask
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from telebot.apihelper import ApiTelegramException

# --- FAKE WEB SERVER TO KEEP RENDER HAPPY ---
app = Flask(__name__)

@app.route('/')
def home():
    return "V5 Ultimate Bot is running beautifully on Render!"

# --- CONFIGURATION ---
TOKEN = '8664807029:AAGNevBQxxCt3l1CI-g6QP6LnhKRa3D2_pQ'  # Put your bot token here
CHANNEL_USERNAME = '@deepseek_deepAi' 
CHANNEL_URL = 'https://t.me/deepseek_deepAi'
DB_FILE = 'database.json'

bot = telebot.TeleBot(TOKEN)

# --- THREAD-SAFE STATE & DATABASE ---
db_lock = threading.Lock()
active_polls = {} # Key is now a unique poll_id
setup_sessions = {}

def load_db():
    global active_polls
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, 'r') as f:
                active_polls = json.load(f)
        except json.JSONDecodeError:
            active_polls = {}

def save_db():
    with open(DB_FILE, 'w') as f:
        json.dump(active_polls, f)

load_db()

# --- BACKGROUND EXPIRATION TIMER ---
def expiration_checker():
    """Runs in the background and auto-closes polls when time is up."""
    while True:
        time.sleep(60)
        current_time = time.time()
        expired_polls = []
        
        with db_lock:
            for poll_id, poll in active_polls.items():
                if poll.get('expires_at') and poll['expires_at'] != 0:
                    if current_time >= poll['expires_at']:
                        expired_polls.append(poll_id)
        
        for poll_id in expired_polls:
            end_poll_logic(poll_id, auto_expired=True)

# --- HELPERS & MENUS ---

def is_subscribed(user_id):
    """Checks if a user is subscribed to the channel."""
    try:
        status = bot.get_chat_member(CHANNEL_USERNAME, user_id).status
        return status in ['member', 'administrator', 'creator']
    except ApiTelegramException:
        return True 

def force_sub_markup():
    """Generates the subscription verification buttons."""
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("📢 Subscribe to Channel", url=CHANNEL_URL))
    markup.add(InlineKeyboardButton("✅ I Have Subscribed", callback_data="check_sub"))
    return markup

def main_menu():
    """Generates the permanent bottom keyboard buttons."""
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row(KeyboardButton("📝 Create Poll"), KeyboardButton("👀 Manage My Polls"))
    markup.row(KeyboardButton("🛑 End a Poll"), KeyboardButton("🗑 Cancel Setup"))
    return markup

def generate_poll_markup(poll_id):
    """Generates the Inline Buttons for voting."""
    poll = active_polls[poll_id]
    markup = InlineKeyboardMarkup()
    
    if poll.get('mode') == 'random':
        text = f"🎲 Join Randomly ({len(poll['voted'])})"
        markup.add(InlineKeyboardButton(text, callback_data=f"v:{poll_id}:rand"))
    else:
        for i, group in enumerate(poll['groups']):
            if group['limit'] == 0:
                status = f"🟢 {len(group['members'])} Votes"
            else:
                status = "🔴 Full" if len(group['members']) >= group['limit'] else f"🟢 {len(group['members'])}/{group['limit']}"
            
            text = f"{group['name']} - {status}"
            markup.add(InlineKeyboardButton(text, callback_data=f"v:{poll_id}:{i}"))
            
    return markup

def get_poll_text(poll_id):
    """Generates the public view of the poll."""
    poll = active_polls[poll_id]
    mode_text = "🎲 **Random Assignment Mode**" if poll.get('mode') == 'random' else "🖐 **Manual Selection Mode**"
    
    expire_text = ""
    if poll.get('expires_at') and poll['expires_at'] != 0:
        hours_left = round((poll['expires_at'] - time.time()) / 3600, 1)
        expire_text = f"⏳ **Closes automatically in:** {hours_left} hours\n"

    cap_text = str(poll['total_capacity']) if poll['total_capacity'] > 0 else "∞ (Unlimited)"
    
    text = f"📋 **{poll['title']}**\n{mode_text}\n{expire_text}\n"
    text += f"Total Votes: {len(poll['voted'])}/{cap_text}\n"
    text += "🔒 *Names are hidden to prevent bias.*\n\n"
    return text

def get_results_text(poll_id):
    """Generates the final revealed results."""
    poll = active_polls[poll_id]
    cap_text = str(poll['total_capacity']) if poll['total_capacity'] > 0 else "∞ (Unlimited)"
    
    text = f"📊 **RESULTS: {poll['title']}**\n"
    text += f"Total Votes: {len(poll['voted'])}/{cap_text}\n\n"
    
    for group in poll['groups']:
        lim_text = "∞" if group['limit'] == 0 else str(group['limit'])
        text += f"🔹 **{group['name']} ({len(group['members'])}/{lim_text}):**\n"
        if not group['members']:
            text += " - (No members)\n"
        else:
            for member in group['members']:
                text += f" - {member['display']}\n"
        text += "\n"
    return text

def update_all_poll_messages(poll_id):
    """Updates the poll everywhere it was shared."""
    poll = active_polls[poll_id]
    text = get_poll_text(poll_id)
    markup = generate_poll_markup(poll_id)

    # Update original chat message (if applicable)
    if poll.get('chat_id') and poll.get('message_id'):
        try: bot.edit_message_text(text, chat_id=poll['chat_id'], message_id=poll['message_id'], reply_markup=markup, parse_mode='Markdown')
        except Exception: pass
    
    # Update all inline shared messages
    for inline_id in poll.get('inline_message_ids', []):
        try: bot.edit_message_text(text, inline_message_id=inline_id, reply_markup=markup, parse_mode='Markdown')
        except Exception: pass

# --- MAIN BOT COMMANDS ---

@bot.message_handler(commands=['start'])
def send_welcome(message):
    if not is_subscribed(message.from_user.id):
        bot.send_message(message.chat.id, f"👋 Welcome! Before using this bot, you **MUST** subscribe to our channel.\n\nPlease join {CHANNEL_URL} and click verify.", reply_markup=force_sub_markup())
        return
    
    text = "👋 **Welcome to the Advanced Group Maker Bot!**\n\nUse the menu below to create or manage polls."
    bot.send_message(message.chat.id, text, reply_markup=main_menu(), parse_mode='Markdown')

@bot.message_handler(commands=['create'])
@bot.message_handler(func=lambda msg: msg.text == "📝 Create Poll")
def start_setup(message):
    user_id = message.from_user.id
    if not is_subscribed(user_id):
        bot.send_message(message.chat.id, "⛔️ You must subscribe first!", reply_markup=force_sub_markup())
        return

    setup_sessions[user_id] = {'groups': []}
    msg = bot.send_message(message.chat.id, "Let's create a poll! 🛠\n\n**Step 1:** What is the Title or Purpose of this poll?")
    bot.register_next_step_handler(msg, process_title)

@bot.message_handler(commands=['cancel'])
@bot.message_handler(func=lambda msg: msg.text == "🗑 Cancel Setup")
def cancel_setup(message):
    user_id = message.from_user.id
    if user_id in setup_sessions:
        del setup_sessions[user_id]
        bot.send_message(message.chat.id, "🗑 **Setup Cancelled.**", parse_mode='Markdown')
    else:
        bot.send_message(message.chat.id, "You have no active setup to cancel.")

# --- STEP-BY-STEP CREATION LOGIC ---

def process_title(message):
    user_id = message.from_user.id
    if message.text in ['/cancel', '🗑 Cancel Setup']:
        if user_id in setup_sessions: del setup_sessions[user_id]
        return bot.send_message(message.chat.id, "Setup cancelled.")

    setup_sessions[user_id]['title'] = message.text
    msg = bot.send_message(message.chat.id, "**Step 2:** How many HOURS until this poll auto-expires? (Send `0` for no limit)")
    bot.register_next_step_handler(msg, process_expiration)

def process_expiration(message):
    user_id = message.from_user.id
    if message.text in ['/cancel', '🗑 Cancel Setup']:
        if user_id in setup_sessions: del setup_sessions[user_id]
        return bot.send_message(message.chat.id, "Setup cancelled.")

    try:
        hours = float(message.text)
        setup_sessions[user_id]['expires_at'] = (time.time() + (hours * 3600)) if hours > 0 else 0
    except ValueError:
        msg = bot.send_message(message.chat.id, "❌ Please send a valid number. Try again:")
        return bot.register_next_step_handler(msg, process_expiration)

    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("🖐 Users Pick Manually", callback_data="mode_manual"))
    markup.add(InlineKeyboardButton("🎲 Bot Picks Randomly", callback_data="mode_random"))
    bot.send_message(message.chat.id, "**Step 3:** How should users be assigned?", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data in ['mode_manual', 'mode_random'])
def process_mode(call):
    user_id = call.from_user.id
    if user_id not in setup_sessions: return
    
    setup_sessions[user_id]['mode'] = call.data.split('_')[1]
    bot.delete_message(call.message.chat.id, call.message.message_id)
    
    # ANTI-BIAS FEATURE
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("✅ Yes, allow changes", callback_data="change_yes"))
    markup.add(InlineKeyboardButton("❌ No, lock their vote", callback_data="change_no"))
    bot.send_message(call.message.chat.id, "**Step 4:** Allow users to change their vote after clicking?", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data in ['change_yes', 'change_no'])
def process_changes(call):
    user_id = call.from_user.id
    if user_id not in setup_sessions: return
    
    setup_sessions[user_id]['allow_changes'] = (call.data == "change_yes")
    bot.delete_message(call.message.chat.id, call.message.message_id)
    
    msg = bot.send_message(call.message.chat.id, "**Step 5:** How many groups/options do you want? (Send a number)", parse_mode='Markdown')
    bot.register_next_step_handler(msg, process_num_groups)

def process_num_groups(message):
    user_id = message.from_user.id
    if message.text in ['/cancel', '🗑 Cancel Setup']:
        if user_id in setup_sessions: del setup_sessions[user_id]
        return bot.send_message(message.chat.id, "Setup cancelled.")

    if not message.text.isdigit() or int(message.text) < 1:
        msg = bot.send_message(message.chat.id, "❌ Please send a valid number. Try again:")
        return bot.register_next_step_handler(msg, process_num_groups)

    setup_sessions[user_id]['num_groups'] = int(message.text)
    setup_sessions[user_id]['current_group'] = 1

    msg = bot.send_message(message.chat.id, f"What is the **Name** for Option 1?")
    bot.register_next_step_handler(msg, process_group_name)

def process_group_name(message):
    user_id = message.from_user.id
    if message.text in ['/cancel', '🗑 Cancel Setup']:
        if user_id in setup_sessions: del setup_sessions[user_id]
        return bot.send_message(message.chat.id, "Setup cancelled.")

    setup_sessions[user_id]['temp_name'] = message.text
    msg = bot.send_message(message.chat.id, f"What is the **Member Limit** for '{message.text}'?\n*(Send `0` for Unlimited)*", parse_mode='Markdown')
    bot.register_next_step_handler(msg, process_group_limit)

def process_group_limit(message):
    user_id = message.from_user.id
    if message.text in ['/cancel', '🗑 Cancel Setup']:
        if user_id in setup_sessions: del setup_sessions[user_id]
        return bot.send_message(message.chat.id, "Setup cancelled.")

    if not message.text.isdigit() or int(message.text) < 0:
        msg = bot.send_message(message.chat.id, "❌ Limit must be 0 or higher. Try again:")
        return bot.register_next_step_handler(msg, process_group_limit)

    session = setup_sessions[user_id]
    session['groups'].append({'name': session['temp_name'], 'limit': int(message.text), 'members': []})

    if session['current_group'] < session['num_groups']:
        session['current_group'] += 1
        msg = bot.send_message(message.chat.id, f"What is the **Name** for Option {session['current_group']}?")
        bot.register_next_step_handler(msg, process_group_name)
    else:
        # Generate Unique Poll ID
        poll_id = str(uuid.uuid4())[:8]
        total_cap = sum(g['limit'] for g in session['groups'])
        if any(g['limit'] == 0 for g in session['groups']): total_cap = 0
        
        with db_lock:
            active_polls[poll_id] = {
                'owner': user_id,
                'title': session['title'],
                'mode': session['mode'],
                'allow_changes': session['allow_changes'],
                'expires_at': session.get('expires_at', 0),
                'groups': session['groups'],
                'voted': {},
                'total_capacity': total_cap,
                'chat_id': message.chat.id,
                'message_id': None,
                'inline_message_ids': []
            }
            save_db()
        
        del setup_sessions[user_id]
        
        # Send Poll to the chat it was created in
        sent_msg = bot.send_message(message.chat.id, get_poll_text(poll_id), reply_markup=generate_poll_markup(poll_id), parse_mode='Markdown')
        
        with db_lock:
            active_polls[poll_id]['message_id'] = sent_msg.message_id
            save_db()

        # Provide the Inline Share Button!
        share_markup = InlineKeyboardMarkup()
        share_markup.add(InlineKeyboardButton("↗️ Share this Poll to a Group", switch_inline_query=poll_id))
        bot.send_message(message.chat.id, "🎉 **Poll Created!** Click below to forward it to your groups.", reply_markup=share_markup, parse_mode='Markdown')

# --- INLINE QUERY HANDLER (FOR SHARING TO GROUPS) ---

@bot.inline_handler(func=lambda query: True)
def inline_query(query):
    poll_id = query.query.strip()
    if poll_id not in active_polls:
        return # Poll doesn't exist
    
    poll = active_polls[poll_id]
    
    content = telebot.types.InputTextMessageContent(get_poll_text(poll_id), parse_mode='Markdown')
    markup = generate_poll_markup(poll_id)
    
    result = telebot.types.InlineQueryResultArticle(
        id=poll_id,
        title=f"Share: {poll['title']}",
        description="Click here to send your poll to a chat!",
        input_message_content=content,
        reply_markup=markup
    )
    bot.answer_inline_query(query.id, [result], cache_time=1)

# --- INLINE BUTTON CALLBACKS (VOTING) ---

@bot.callback_query_handler(func=lambda call: call.data == "check_sub")
def handle_sub_check(call):
    if is_subscribed(call.from_user.id):
        bot.answer_callback_query(call.id, "✅ Verification Successful!", show_alert=True)
        bot.delete_message(call.message.chat.id, call.message.message_id)
    else:
        bot.answer_callback_query(call.id, "❌ You have not subscribed yet.", show_alert=True)

@bot.callback_query_handler(func=lambda call: call.data.startswith('v:'))
def handle_vote(call):
    if not is_subscribed(call.from_user.id):
        bot.answer_callback_query(call.id, "⛔️ You must subscribe to our channel to vote!", show_alert=True)
        return

    # Parse data: "v:poll_id:group_index_or_rand"
    parts = call.data.split(':')
    poll_id = parts[1]
    action = parts[2]
    
    user_id = str(call.from_user.id)
    username = f" (@{call.from_user.username})" if call.from_user.username else ""
    display_name = f"{call.from_user.first_name}{username}"

    if poll_id not in active_polls:
        return bot.answer_callback_query(call.id, "This poll has ended.", show_alert=True)

    with db_lock:
        poll = active_polls[poll_id]
        
        # Save inline message ID if voted from a shared group
        if call.inline_message_id and call.inline_message_id not in poll['inline_message_ids']:
            poll['inline_message_ids'].append(call.inline_message_id)

        # ANTI-BIAS: Check if changes are allowed
        if user_id in poll['voted'] and not poll['allow_changes']:
            return bot.answer_callback_query(call.id, "⛔️ You are not allowed to change your vote in this poll!", show_alert=True)

        # Remove old vote
        if user_id in poll['voted']:
            old_group_idx = poll['voted'][user_id]
            poll['groups'][old_group_idx]['members'] = [m for m in poll['groups'][old_group_idx]['members'] if m['id'] != user_id]

        # Process Vote
        if action == "rand":
            available = [i for i, g in enumerate(poll['groups']) if g['limit'] == 0 or len(g['members']) < g['limit']]
            if not available:
                return bot.answer_callback_query(call.id, "All groups are full!", show_alert=True)
            group_index = random.choice(available)
            popup_message = "🎲 Vote recorded! Your assigned group is kept secret until the poll ends!"
        else:
            group_index = int(action)
            g_limit = poll['groups'][group_index]['limit']
            if g_limit != 0 and len(poll['groups'][group_index]['members']) >= g_limit:
                return bot.answer_callback_query(call.id, "Group is full! Pick another.", show_alert=True)
            popup_message = f"Success! You joined {poll['groups'][group_index]['name']}."

        poll['voted'][user_id] = group_index
        poll['groups'][group_index]['members'].append({'id': user_id, 'display': display_name})
        save_db()

    # Alert user and Update UI everywhere
    bot.answer_callback_query(call.id, popup_message, show_alert=True)
    update_all_poll_messages(poll_id)

    # Auto-Notify Creator if full (Only if not unlimited)
    if poll['total_capacity'] > 0 and len(poll['voted']) >= poll['total_capacity']:
        try: bot.send_message(poll['owner'], f"🎉 **Attention:** Your poll '{poll['title']}' is now full!", parse_mode='Markdown')
        except Exception: pass

# --- POLL MANAGEMENT (END / VIEW) ---

def end_poll_logic(poll_id, auto_expired=False):
    """Ends the poll, reveals results to all chats, and exports a text file."""
    with db_lock:
        if poll_id not in active_polls: return
        poll = active_polls[poll_id]
        results_text = get_results_text(poll_id)
        
        prefix = "⏳ **AUTO-EXPIRED:** Time is up!\n\n" if auto_expired else "🛑 **Poll manually closed.**\n\n"
        
        # Update original chat
        if poll.get('chat_id'):
            bot.send_message(poll['chat_id'], f"{prefix}{results_text}", parse_mode='Markdown')
            try: bot.edit_message_reply_markup(poll['chat_id'], poll['message_id'], reply_markup=None)
            except Exception: pass
            
            # Send file
            doc = BytesIO(results_text.replace('*', '').encode('utf-8'))
            doc.name = f"{poll['title']}_Results.txt"
            bot.send_document(poll['chat_id'], doc, caption="📁 Downloadable Results")
            
        # Update Inline messages
        for inline_id in poll.get('inline_message_ids', []):
            try: bot.edit_message_text(f"{prefix}{results_text}", inline_message_id=inline_id, parse_mode='Markdown')
            except Exception: pass

        del active_polls[poll_id]
        save_db()

@bot.message_handler(func=lambda msg: msg.text in ["👀 Manage My Polls", "🛑 End a Poll"])
def list_my_polls(message):
    user_id = message.from_user.id
    my_polls = {k: v for k, v in active_polls.items() if v['owner'] == user_id}
    
    if not my_polls:
        return bot.send_message(message.chat.id, "You have no active polls right now.")

    action = "view" if "Manage" in message.text else "end"
    
    markup = InlineKeyboardMarkup()
    for pid, poll in my_polls.items():
        markup.add(InlineKeyboardButton(f"{poll['title']}", callback_data=f"manage:{action}:{pid}"))
        
    bot.send_message(message.chat.id, f"Select a poll to {action}:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('manage:'))
def handle_management(call):
    parts = call.data.split(':')
    action = parts[1]
    poll_id = parts[2]
    
    if poll_id not in active_polls:
        return bot.answer_callback_query(call.id, "Poll no longer exists.", show_alert=True)
        
    if action == "view":
        bot.send_message(call.message.chat.id, f"👀 **Current Progress:**\n\n{get_results_text(poll_id)}", parse_mode='Markdown')
        bot.answer_callback_query(call.id)
    elif action == "end":
        end_poll_logic(poll_id, auto_expired=False)
        bot.answer_callback_query(call.id, "Poll Ended!", show_alert=True)
        bot.delete_message(call.message.chat.id, call.message.message_id)

# --- FALLBACK / UNDEFINED COMMANDS (ROADMAP) ---

@bot.message_handler(func=lambda message: True)
def undefined_commands(message):
    """Catches all unrecognized text/commands and provides the roadmap."""
    roadmap = (
        "🤖 **Bot Roadmap & Instructions**\n\n"
        "I didn't understand that. Here is how to use me:\n\n"
        "1️⃣ **Join the Channel:** You must join our channel to use the bot.\n"
        "2️⃣ **Create a Poll:** Click `📝 Create Poll` in the menu below.\n"
        "3️⃣ **Share:** Once created, click the 'Share to Group' button to send it to your friends!\n"
        "4️⃣ **Monitor:** Click `👀 Manage My Polls` to secretly check who has joined.\n"
        "5️⃣ **Finish:** Click `🛑 End a Poll` to lock the poll and show everyone the results.\n\n"
    )
    bot.send_message(message.chat.id, roadmap, parse_mode='Markdown')

# --- STARTING THE BOT & WEB SERVER (FOR RENDER) ---

def run_bot():
    print("V5 Ultimate Bot Running...")
    bot.polling(non_stop=True)

if __name__ == "__main__":
    # Start the expiration checker in the background
    threading.Thread(target=expiration_checker, daemon=True).start()
    
    # Start the bot on a separate background thread
    threading.Thread(target=run_bot, daemon=True).start()
    
    # Start the fake web server so Render doesn't shut down the app
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
