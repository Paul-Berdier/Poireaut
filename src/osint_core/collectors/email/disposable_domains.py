"""Curated list of disposable / temporary email providers.

Sourced from the community list at
https://github.com/disposable-email-domains/disposable-email-domains —
this is a condensed selection of the most common ones. For exhaustive
coverage, subclass EmailDomainExtractor and pass your own set via
`disposable_domains=`.
"""

DISPOSABLE_DOMAINS: frozenset[str] = frozenset(
    {
        # Top-tier temporary mail services
        "mailinator.com", "guerrillamail.com", "guerrillamail.net",
        "guerrillamail.org", "guerrillamail.biz", "grr.la", "spam4.me",
        "sharklasers.com", "pokemail.net", "tempinbox.com",
        "10minutemail.com", "10minutemail.net", "20minutemail.com",
        "33mail.com", "temp-mail.org", "temp-mail.io", "tempmail.com",
        "tempmailaddress.com", "tempmail.ninja", "throwawaymail.com",
        "throwaway.email", "yopmail.com", "yopmail.net", "yopmail.fr",
        "cool.fr.nf", "jetable.fr.nf", "nospam.ze.tc", "courriel.fr.nf",
        "nomail.xl.cx", "mail-temporaire.fr",
        "dispostable.com", "maildrop.cc", "mailnesia.com",
        "fakeinbox.com", "getairmail.com", "emailondeck.com",
        "fake-mail.com", "getnada.com", "meltmail.com", "mintemail.com",
        "mohmal.com", "trashmail.com", "trash-mail.com", "trashmail.net",
        "tmailinator.com", "tyldd.com", "zippymail.in", "vomoto.com",
        "mytemp.email", "emaildrop.io", "e4ward.com", "mvrht.com",
        # Privacy forwarders commonly used for signups
        "simplelogin.io", "simplelogin.co", "anonaddy.me", "anonaddy.com",
        "duck.com", "duckduckgo.com",  # DuckDuckGo Email Protection relay
        # AnonAddy / SimpleLogin generic suffixes (there are more)
        "aleeas.com",
        # Apple's Hide My Email
        "privaterelay.appleid.com",
        # Firefox Relay
        "mozmail.com",
        # Miscellaneous
        "armyspy.com", "cuvox.de", "dayrep.com", "einrot.com",
        "fleckens.hu", "gustr.com", "jourrapide.com", "rhyta.com",
        "superrito.com", "teleworm.us",
        "mailcatch.com", "mailmoat.com", "notsharingmy.info",
        "objectmail.com", "proxymail.eu", "rcpt.at", "safe-mail.net",
        "sneakemail.com", "spambog.com", "spambog.de", "spamfree24.org",
        "spamhole.com", "spamhouse.net", "spamify.com", "spaml.com",
        "tempr.email", "trbvm.com", "wegwerfmail.de", "wegwerfmail.net",
        "wegwerfmail.org", "wh4f.org", "whyspam.me",
        # More temp mail
        "binkmail.com", "bobmail.info", "chammy.info",
        "devnullmail.com", "disposableaddress.com",
        "disposableemailaddresses.com", "discardmail.com",
        "discardmail.de", "doiea.com", "dumpandjunk.com",
        "eyepaste.com", "hostcalls.com", "incognitomail.org",
        "imgof.com", "junkmail.com", "klzlk.com", "kurzepost.de",
        "mailbox.in.ua", "mailcatch.org", "mailforspam.com",
        "mailimate.com", "mailmetrash.com", "mailsac.com",
        "mailshell.com", "mbx.cc", "mint.xteam.pl",
        "one-off.com", "opayq.com", "putthisinyourspamdatabase.com",
        "receiveee.com", "reconmail.com", "regbypass.com",
        "safersignup.de", "sendspamhere.com", "shortmail.net",
        "slippery.net", "slopsbox.com", "smellfear.com",
        "snakemail.com", "sogetthis.com", "sweetxxx.de",
        "tempemail.net", "tempymail.com", "trickmail.net",
    }
)
