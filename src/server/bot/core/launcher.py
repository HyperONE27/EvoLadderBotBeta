import discord

intents = discord.Intents.default()
intents.message = True
intents.message_content = True
intents.members = True

bot = EvoLadderBot(command_prefix)

def main():
    pass

if __name__ == "__main__":
    main()