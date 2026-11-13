interface DonationProvider {
  icon: string;
  hosts: string[];
}

const donationProviders: DonationProvider[] = [
  { icon: 'buymeacoffee', hosts: ['buymeacoffee.com'] },
  { icon: 'kofi', hosts: ['ko-fi.com'] },
  { icon: 'paypal', hosts: ['paypal.com', 'paypal.me'] },
  { icon: 'opencollective', hosts: ['opencollective.com'] },
  { icon: 'liberapay', hosts: ['liberapay.com'] },
];

export function getDonationIcon(url: string | null | undefined): string {
  const value = url?.trim();
  if (!value) return 'heart';

  try {
    const parsedUrl = new URL(
      /^[a-z][a-z\d+.-]*:\/\//i.test(value) ? value : `https://${value}`
    );
    const hostname = parsedUrl.hostname.toLowerCase();
    const provider = donationProviders.find(({ hosts }) =>
      hosts.some((host) => hostname === host || hostname.endsWith(`.${host}`))
    );

    return provider?.icon || 'heart';
  } catch {
    return 'heart';
  }
}
