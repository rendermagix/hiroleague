
# Priority
- add Device Name in Device Paring.
- Clean up Message Format
- Add ability to send Commands.
- Allow creating channels/conversations.
- Admin UI - List Devices
- Admin UI - Revoke Devices

# Flutter App/Web
- Upgrade Flutter Packages to latest! Waiting for riverpod_generator to support analyzer ^10, in order to update sqlite3 and many other packages.
- Biometric/Pass/Pattern Lock
- Add ability to send Voice, Image.
- Add ability to respond in Voice.

# Daily Tasks
- Allow showing Agent Execution, Tools, $ Consumption.
- Allow creating Bots/Selecting them.

# Server/CLI
- Log what really matters
- Upgrade Python Packages to latest!
- when server time and device time are different, how would you define the timestamp, inbound to device, or ourbound to server..
- Better formatting of CLI UI, showing waiting animation, showing Colors, 
- Refactor CLI UI to be more consistent and easier to use.
- cli uninstall will teardown a single workspace, and uninstall cli - I think uninstall should teardown all workspaces first.
- workspace remove doesnt check if auto start is removed first (teardown) - so some services will stay orphaned.

# Admin UI
- Admin UI - Figuring out Missing parts and initial arrangement
- Admin UI - Workspace Restart not working - Deep Issue with Python Spawning.
- cleaning up orphaned channel processes, what is the best approach?
- Admin UI - Logs should be a Tool, Log should have colors.
- Fine Tune Tools for better utilization
- Work on Admin UI Security
- Show Scheduled Tasks schtasks
- clicking long actions in admin ui should show a progress bar. like start, delete workspaces, etc...
- show a message back online when restarting admin ui.
- calling http on gateway ws causes an error in gateway code in terminal.
- allow gateway to edit instance name like workspace.

# Refactoring
- Gateway

# Github Cleanup
- setup branches.
- Add Releases

# Mint Docs
- Keep polishing the docs as you build the features.
- Add Change Log to Mintdocs.
- Need the final domain name.
- Publish Online and link to Github
- Versions
- Languages

# General Features
- Resource Usage (CPU/Memory/Disk/Network/LLM$)
- security policy
- add browser tool
- install tools as plugins
- Add Memory
- Add RAG
- Add Whatsapp Channel
- Add Permission system.
- Add Tool Plugins.
- Add Bot Plugins.
- Add Memory Plugins.
- Add Plugin Discovery, Plugin Submission, rating, reviews, scanning, ecosystem...
- add versioning.

# Security

- Conversations should be encrypted. in case they are stolen, they should be unreadable.
- When a device is revoked, the gateway relay is not notified and it keeps accepting messages from devices. also the devices are not checked that they are still valid, not in server, not in gateway.
- Need a command that is a Health/Doctor, that checks validity of the installation, latest version, status, valid file structure, etc... can be also used for debugging and sending bug reports.

# Big Design Ideas

- Auto Test Cases.
- Auto Security Checks.
- Keep reviewing similar projects to improve security and usability.
- Easiest User Experience Setup.
- Win/Mac/Linux Support.
- Automate building process (local and release)
- Need to consider Version Upgrades and breaking changes and how data, devices are affected and how versioning can solidly handle them all.

# Big Ideas

- Focus on 
	- Personal Assistance
	- Mental Wellness
	- Being a Loyal Friend/Visual Connection
	- Life Automation
- Leverage
	- Phone Connection
	- PC Connection
	- Home Connection
- Additional Help
	- Family Connection/Assistance
	- Home Assistance
- Values
	- Security and Control - Not yet another OpenClaw Clone
	- Warm/Friendly Connection
	- Accessibility
- Goals
	- Build in Public
	- Easy to Install
	- Many Common Features by default
	- Loosely coupled Interfaces (Plugin Architecture)
- Design
    - Make very flexible design
    - Ability to Extend without breaking
    - Self Modifying Code, Prompt to Code
    - Build Pages with Prompts - Like Lego Blocks

# Use Cases:
- Find information in my chats, files
- Bot to learn about me, my family, preferences, etc... and offer therapy
- Get web information on my behalf from social media, etc.. and send directly to me via chat
- Help me Organize, schedule and remind me of important things in my life
- Use my location, preferences, and my family's and kid's location and preferences for better life organiaztion. ex: kids are late, Kids are home, wife just left, stranger around home, provide info about places i am visiting.
- Access my home's cameras, wifi, iot, for better control and insight, notifications.

# Completed

- Initial Bootstrapping of Project.
  - phbcli
  - phbgateway
  - phb-channel-sdk (Devices Channel)
  - Flutter App Web
- phbcli Outbound Not Working
- Add xLogger Custom Logging module for better terminal tracking.
- introduce workspace concept for better organization of config files.
- introduce gateway instances concept for better organization of gateway config files.
- (tool-architecture) separate cli from functionality, and allow an api for the website.
- Refactor phbcli into organized folders - runtime/tools/commands/services/domain
- Move all CLI commands to new tool design
- Move Docs to Mintdocs.
- Describe progressive Architecture in MintDocs, add Diagrams.
- Add Home Page
- Create Flutter Android App
- Admin UI - Workspace should be a Global Dropdown
- Admin UI - Allow Reloading Workspace.
- Admin UI - Add Device QR Code
- Admin UI - Allow Loading Local Gateways
- when adding a workspace in admin ui, show public key ONCE.
- Admin/Mobile/Web - Pair using QR Code
- Fix Flutter Package Versions.


# Quick Links

- LLM Fit - Find which Models run on your machine.
https://github.com/AlexsJones/llmfit/tree/main


# UI Design Ideas

https://www.figma.com/design/xwFjWgtfvUDugureqPv7MP/Chatting-App-UI-Kit-Design-%7C-E-Chat-%7C-Figma--Community-?node-id=21-122&p=f&t=rAGxICp5xJ3H5YBP-0


https://www.figma.com/design/H7QknI56ActTeuuulFlFC6/BrainBox-Ai-ChatBot-Mobile-App-Full-100--Free-UI-Kit--Community-?node-id=0-1&p=f&t=lJd4fxSfCpseam0C-0