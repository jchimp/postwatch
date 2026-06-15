import requests
import json

session = requests.Session()
base_url = "http://localhost:5000"

# Login
login_data = {"username": "admin", "password": "admin"}
response = session.post(f"{base_url}/login", data=login_data)
print(f"Login: {response.status_code}\n")

# Test aggregation
print("All Hosts (aggregated):")
response = session.get(f"{base_url}/api/chart/daily/all?days=7")
all_data = response.json()
if all_data:
    first_day = all_data[0]
    print(f"  Day: {first_day['day']}")
    print(f"  Sent: {first_day['sent']}")
    print(f"  Deferred: {first_day['deferred']}")
    print(f"  Bounced: {first_day['bounced']}")
    print(f"  Rejected: {first_day['rejected']}")

# Test Agent 1 alone
print("\nAgent 1 only:")
agent1_url = "http%3A%2F%2Flocalhost%3A5100"
response = session.get(f"{base_url}/api/chart/daily/{agent1_url}?days=7")
agent1_data = response.json()
if agent1_data:
    first_day = agent1_data[0]
    print(f"  Day: {first_day['day']}")
    print(f"  Sent: {first_day['sent']}")

# Test Agent 2 alone
print("\nAgent 2 only:")
agent2_url = "http%3A%2F%2Flocalhost%3A5101"
response = session.get(f"{base_url}/api/chart/daily/{agent2_url}?days=7")
agent2_data = response.json()
if agent2_data:
    first_day = agent2_data[0]
    print(f"  Day: {first_day['day']}")
    print(f"  Sent: {first_day['sent']}")

# Verify aggregation math
print("\nVerification:")
if all_data and agent1_data and agent2_data:
    all_sent = all_data[0]['sent']
    agent1_sent = agent1_data[0]['sent']
    agent2_sent = agent2_data[0]['sent']
    expected = agent1_sent + agent2_sent

    print(f"  Agent1 sent + Agent2 sent = {agent1_sent} + {agent2_sent} = {expected}")
    print(f"  All hosts sent = {all_sent}")
    print(f"  Match: {all_sent == expected}")
