import garth, getpass
email = input("Garmin email: ")
password = getpass.getpass("Garmin password: ")
client = garth.Client()
client.login(email, password)
print("Access token:", client.oauth1_token.oauth_token)

