import asyncio
import yaml
import os
from datetime import datetime


# Replace the static config loading with a Config class
class ConfigWatcher:
    def __init__(self, config_path='config.yaml', reload_interval=3):
        self.config_path = config_path
        self.reload_interval = reload_interval
        self.last_modified = None
        self.config = {}
        self._watch_task = None

    async def start_watching(self):
        """Start the config file watching task"""
        self._watch_task = asyncio.create_task(self._watch_config())
        print(f"📋 Started watching {self.config_path} for changes")

    async def stop_watching(self):
        """Stop the config file watching task"""
        if self._watch_task:
            self._watch_task.cancel()
            await asyncio.gather(self._watch_task, return_exceptions=True)

    def get(self, key, default=None):
        """Get a value from config with a default fallback"""
        return self.config.get(key, default)

    async def _watch_config(self):
        """Watch config file locally"""
        while True:
            try:
                if os.path.exists(self.config_path):
                    mtime = os.path.getmtime(self.config_path)
                    # print(f"🔄 Currently watching {self.config_path} for changes")
                    if self.last_modified != mtime:
                        with open(self.config_path, 'r') as f:
                            new_config = yaml.safe_load(f)
                            
                            if new_config != self.config:
                                old_config = self.config.copy()
                                self.config = new_config
                                self.last_modified = mtime
                                print(f"🔄 Config reloaded at {datetime.now().strftime('%H:%M:%S')}")
                                # Log significant changes
                                self._log_config_changes(old_config, new_config)
                            
            except Exception as e:
                print(f"❌ Error reading config: {e}")
                self.config = {}                
            await asyncio.sleep(self.reload_interval)

    def _log_config_changes(self, old_config, new_config):
        """Log significant changes in configuration"""
        def get_nested(config, path, default=None):
            current = config
            for part in path.split('.'):
                if isinstance(current, dict):
                    current = current.get(part, default)
                else:
                    return default
            return current

        # Important settings to monitor
        watch_paths = [
            'order_settings.use_take_profit',
            'order_settings.use_trailing_stop',
            'order_settings.overrides.trail_amount',
            'order_settings.overrides.stop_loss',
            'order_settings.overrides.take_profit',
            'order_settings.overrides.quantity',
            'order_settings.overrides.tp_quantity',
            'order_settings.overrides.ts_quantity',
            'order_settings.timeouts.fill_or_cancel',
            'order_settings.timeouts.bracket_fill'
        ]

        for path in watch_paths:
            old_value = get_nested(old_config, path)
            new_value = get_nested(new_config, path)
            if old_value != new_value:
                print(f"📝 Config change: {path}: {old_value} -> {new_value}")

    async def update(self, updates: dict) -> None:
        """
        Update config file with new values.
        
        Args:
            updates: Dictionary of dot-notation paths and their new values
                    e.g. {'order_settings.overrides.quantity': 2}
        """
        try:
            # Read current config
            if os.path.exists(self.config_path):
                with open(self.config_path, 'r') as f:
                    current_config = yaml.safe_load(f) or {}
            else:
                current_config = {}

            # Apply updates
            for path, value in updates.items():
                self._update_nested_dict(current_config, path.split('.'), value)

            # Write updated config
            with open(self.config_path, 'w') as f:
                yaml.dump(current_config, f, default_flow_style=False)

            # Update internal state
            self.config = current_config
            self.last_modified = os.path.getmtime(self.config_path)
            
            print(f"✅ Config updated successfully at {datetime.now().strftime('%H:%M:%S')}")
            
        except Exception as e:
            print(f"❌ Error updating config: {e}")
            raise

    def _update_nested_dict(self, d: dict, keys: list, value: any) -> None:
        """Helper method to update nested dictionary using a list of keys"""
        for key in keys[:-1]:
            d = d.setdefault(key, {})
        d[keys[-1]] = value