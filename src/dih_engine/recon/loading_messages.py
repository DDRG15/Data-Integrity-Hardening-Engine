"""
Loading-screen flavor text for the Seer V4 CLI.

Three moods — pick one at random for each occasion:
  waiting()  -- while the ThreadPoolExecutor is probing URLs
  success()  -- after the Intelligence Report is printed
  failure()  -- when all probes fail and only a diagnostic CSV is saved
"""
import random

WAITING = [
    "Bribing the hamster...",
    "Waking up the minions...",
    "Feeding the unicorns...",
    "Herding cats...",
    "Petting the llama...",
    "Walking the dog...",
    "Chasing the cat...",
    "Checking the pigeon's flight path...",
    "Polishing the turtle's shell...",
    "Untangling the spaghetti...",
    "Converting bugs to features...",
    "Kindly hold on as our intern quits vim...",
    "Searching for the missing semicolon...",
    "Optimizing the 'Hello World'...",
    "Compiling thoughts...",
    "Refactoring reality...",
    "Checking Stack Overflow...",
    "Switching to the latest JS framework...",
    "Ignoring deprecation warnings...",
    "Dividing by zero...",
    "Looking for the 10x developer...",
    "Waiting for the intern to finish coffee...",
    "Recalculating the cloud's weight...",
    "Reticulating splines...",
    "Summoning Clippy...",
    "Mining diamonds...",
    "Up, Up, Down, Down, Left, Right, Left, Right, B, A...",
    "Consulting the oracle...",
    "Winter is coming...",
    "Loading the Matrix...",
    "Generating more pylons...",
    "Constructing additional pylons...",
    "Searching for the cake (it's a lie)...",
    "Brewing coffee...",
    "Reheating pizza...",
    "Contemplating the meaning of life...",
    "Checking the weather in the cloud...",
    "Procrastinating effectively...",
    "Asking the rubber duck for advice...",
    "TODO: Insert elevator music...",
    "Still faster than Windows update...",
    "Trying to sound professional...",
]

SUCCESS = [
    "Ship it! \U0001f680",
    "The oracle has spoken.",
    "The rubber duck approves.",
    "Hamster has been fed.",
    "The minions are going back to sleep.",
    "Spaghetti successfully untangled.",
    "Logic successfully applied (somehow).",
    "The cake was a lie, but here's your data.",
]

FAILURE = [
    "The bug has been promoted to feature.",
    "At least it didn't explode.",
    "Don't look at the logs. Just don't.",
    "Everything is fine. Definitely.",
    "Cleaning up the mess...",
    "Windows Update is still at 1%.",
    "Intern has successfully exited Vim.",
    "Returning to my hibernation pod.",
    "Closing the Matrix...",
]


def waiting() -> str:
    return random.choice(WAITING)


def success() -> str:
    return random.choice(SUCCESS)


def failure() -> str:
    return random.choice(FAILURE)
