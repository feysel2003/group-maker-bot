import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from telebot.apihelper import ApiTelegramException

# --- CONFIGURATION ---
TOKEN = '8664807029:AAFWbB2EYSdY90UiqdZjQ2ghYou8Qdjb1tk'
CHANNEL_USERNAME = '@deepseek_deepAi' # Must include the @ 
CHANNEL_URL = 'https://t.me/deepseek_deepAi'

bot = telebot.TeleBot(TOKEN)

# Databases (In a real pro bot, you would use SQLite/PostgreSQL, but dictionaries work for small scale)
active_polls = {} # Stores live polls: {chat_id: {data}}
setup_sessions = {} # Stores user setup progress: {user_id: {setup_data}}

# --- HELPERS ---

def is_subscribed(user_id):
    """Checks if a user is subscribed to the channel."""
    try:
        status = bot.get_chat_member(CHANNEL_USERNAME, user_id).status
        return status in ['member', 'administrator', 'creator']
    except ApiTelegramException:
        # If bot is not admin in channel, or chat not found, allow access to prevent breaking
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
    for i, group in enumerate(poll['groups']):
        text = f"{group['name']} - {len(group['members'])}/{group['limit']} filled"
        markup.add(InlineKeyboardButton(text, callback_data=f"vote_{i}"))
    return markup

def get_poll_text(chat_id):
    poll = active_polls[chat_id]
    total_votes = sum([len(g['members']) for g in poll['groups']])
    text = f"📋 **{poll['title']}**\n\n"
    text += f"Total Votes: {total_votes}/{poll['total_capacity']}\n"
    text += "🔒 *Names are hidden to prevent bias.*\n\n"
    return text

def get_results_text(chat_id):
    poll = active_polls[chat_id]
    total_votes = sum([len(g['members']) for g in poll['groups']])
    text = f"📊 **RESULTS: {poll['title']}**\n"
    text += f"Total Votes: {total_votes}/{poll['total_capacity']}\n\n"
    for group in poll['groups']:
        text += f"🔹 **{group['name']} ({len(group['members'])}/{group['limit']}):**\n"
        if not group['members']:
            text += " - (No members)\n"
        else:
            text += " - " + "\n - ".join(group['members']) + "\n"
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
        "🔹 `/view` - (Admin) Secretly view current results without ending the poll\n"
        "🔹 `/end` - (Admin) Close the poll and reveal names to everyone\n"
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
    msg = bot.send_message(message.chat.id, "**Step 2:** How many groups do you want to create? (Send a number, e.g., 3)")
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
    curr_group = setup_sessions[user_id]['current_group']
    
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
        
        active_polls[chat_id] = {
            'owner': user_id,
            'title': session['title'],
            'groups': session['groups'],
            'voted': {},
            'total_capacity': total_cap,
            'message_id': None
        }
        
        del setup_sessions[user_id] # Clean up session
        
        sent_msg = bot.send_message(chat_id, get_poll_text(chat_id), reply_markup=generate_poll_markup(chat_id), parse_mode='Markdown')
        active_polls[chat_id]['message_id'] = sent_msg.message_id

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
    # Check Sub Before Voting
    if not is_subscribed(call.from_user.id):
        bot.answer_callback_query(call.id, "⛔️ You must subscribe to our channel to vote!", show_alert=True)
        bot.send_message(call.message.chat.id, f"@{call.from_user.username} Please subscribe to vote:", reply_markup=force_sub_markup())
        return

    chat_id = call.message.chat.id
    user_id = call.from_user.id
    user_name = call.from_user.first_name

    if chat_id not in active_polls:
        return bot.answer_callback_query(call.id, "This poll is inactive.", show_alert=True)

    poll = active_polls[chat_id]
    group_index = int(call.data.split('_')[1])
    selected_group = poll['groups'][group_index]

    if user_id in poll['voted']:
        return bot.answer_callback_query(call.id, "You have already voted!", show_alert=True)

    if len(selected_group['members']) >= selected_group['limit']:
        return bot.answer_callback_query(call.id, "Group is full! Pick another.", show_alert=True)

    # Register vote
    poll['voted'][user_id] = group_index
    selected_group['members'].append(user_name)

    bot.answer_callback_query(call.id, f"Success! You joined {selected_group['name']}.")
    bot.edit_message_text(text=get_poll_text(chat_id), chat_id=chat_id, message_id=poll['message_id'], reply_markup=generate_poll_markup(chat_id), parse_mode='Markdown')

    # Notify creator if poll is full, but DON'T end it
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
    
    bot.send_message(chat_id, f"🛑 **Poll officially closed by creator.** Final Results:\n\n{get_results_text(chat_id)}", parse_mode='Markdown')
    bot.edit_message_reply_markup(chat_id, active_polls[chat_id]['message_id'], reply_markup=None) # Remove voting buttons
    del active_polls[chat_id]

@bot.message_handler(commands=['cancel'])
def cancel_poll(message):
    chat_id = message.chat.id
    if chat_id in active_polls and message.from_user.id == active_polls[chat_id]['owner']:
        bot.edit_message_reply_markup(chat_id, active_polls[chat_id]['message_id'], reply_markup=None)
        del active_polls[chat_id]
        bot.send_message(chat_id, "🗑 **Poll deleted.**", parse_mode='Markdown')

# --- FALLBACK / UNDEFINED COMMANDS (ROADMAP) ---
@bot.message_handler(func=lambda message: True)
def undefined_commands(message):
    # Only respond with roadmap if they type something starting with a slash
    if message.text.startswith('/'):
        roadmap = (
            "🤖 **Bot Roadmap & Instructions**\n\n"
            "I didn't understand that command. Here is how to use me:\n\n"
            "1️⃣ **Join the Channel:** You must join our channel to use the bot.\n"
            "2️⃣ **Create a Poll:** Type `/create` and I will ask you step-by-step for the Title, Groups, and Limits.\n"
            "3️⃣ **Monitor:** Type `/view` to secretly check who has joined which group.\n"
            "4️⃣ **Finish:** Type `/end` to lock the poll and show everyone the results.\n\n"
            "Type `/create` to start!"
        )
        bot.send_message(message.chat.id, roadmap, parse_mode='Markdown')

print("Great Bot System Running...")
bot.polling()