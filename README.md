# TzFeedReader
*Basic podcatcher with regex whitelists*

## Configuration
```
# optional
notifiers:
  pushbullet:
    token: secret
    # optional, defaults to all devices
    device: device_iden

#required
feeds:
    SomeFeed:
        url: https://some-url/

        # BasicAuth
        # auth: "user:pass"
        # Url tokens
        auth:
            parameter_name: secret

        output: ~/Downloads

        whitelist:
            - "^MyFilter"
```
