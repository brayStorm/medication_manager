# Medication Manager

A Home Assistant integration for managing household medications with NFC tag support.

## Features

- Track medication inventory for the entire household
- Assign medications to specific people (e.g., family members)
- Scan NFC tags on pill bottles to record doses
- Get reminders when medications are forgotten
- Receive warnings if medications have already been taken
- Get low inventory alerts for timely refills
- Doctor appointment reminders when prescriptions need renewal

## Installation

### HACS (Recommended)

1. Open HACS in your Home Assistant instance
2. Go to Integrations
3. Click the three dots in the top right corner
4. Select "Custom repositories"
5. Add this repository URL
6. Select "Integration" as the category
7. Click "Add"
8. Find and install "Medication Manager"

### Manual Installation

1. Copy the `medication_manager` directory to your Home Assistant `custom_components` directory
2. Restart Home Assistant
3. Go to Configuration → Integrations and add the Medication Manager integration

## Configuration

Configure the integration through the Home Assistant UI:

1. Go to Configuration → Integrations
2. Click "Add Integration"
3. Search for "Medication Manager"
4. Follow the configuration steps to add people and medications

## NFC Tag Support

- Attach NFC tags to medication bottles
- When scanned, the tag will automatically record a dose
- Works with the Home Assistant companion app for mobile scanning
- No additional automations required

## Screenshots

[Screenshots to be added]

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.
