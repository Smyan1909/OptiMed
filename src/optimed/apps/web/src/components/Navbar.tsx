import Link from "next/link";

export default function Navbar() {
  const links = [
    { href: "/", label: "Home" },
    { href: "/chat", label: "Chat" },
    { href: "/patients", label: "Patients" },
  ];

  return (
    <nav className="bg-blue-600">
      <div className="container mx-auto px-4 flex items-center h-16">
        <span className="font-bold text-white text-xl mr-8">OptiMed</span>
        <ul className="flex space-x-6">
          {links.map((link) => (
            <li key={link.href}>
              <Link
                href={link.href}
                className="text-white hover:text-gray-200 transition-colors"
              >
                {link.label}
              </Link>
            </li>
          ))}
        </ul>
      </div>
    </nav>
  );
}