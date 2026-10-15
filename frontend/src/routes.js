import { ArrowLeft, BarChart3, BookOpen, GraduationCap, History, KeyRound, Layers3, LayoutDashboard, LifeBuoy, MessageSquareWarning, ScanFace, ScanLine, Settings, ShieldCheck, UserCheck, UserCog, Users } from "lucide-react";
import { visibleGroups } from "./lib/auth.js";

// The URLs are the ones the app already used; only how they are presented changed.
export const ROUTES = {
  login: "/login",
  superAdmin: "/super-admin",
  portalAdmins: "/super-admin/admins",
  portalIssues: "/super-admin/issues",
  portalAudit: "/super-admin/audit-log",
  changePassword: "/change-password",
  dashboard: "/dashboard",
  courses: "/courses",
  batches: "/batches",
  students: "/users/students",
  staff: "/users/staff",
  members: "/users/members",
  enrollment: "/face-enrollment",
  scanner: "/attendance-scanner",
  reports: "/reports",
  myReports: "/my-reports",
  settings: "/settings"
};

export const PATH_TO_PAGE = Object.fromEntries(Object.entries(ROUTES).map(([page, path]) => [path, page]));

// Pages that also show one issue at an address of its own: /my-reports/12, /super-admin/issues/12.
export const ISSUE_PAGES = ["myReports", "portalIssues"];
const ISSUE_NUMBER = /^[1-9]\d{0,8}$/;

// { page, issueId } for an address. An address that is no page is "home": the account's own start page.
export function locationView(pathname) {
  const page = PATH_TO_PAGE[pathname];
  if (page) return { page, issueId: null };
  for (const id of ISSUE_PAGES) {
    const prefix = `${ROUTES[id]}/`;
    const rest = pathname.startsWith(prefix) ? pathname.slice(prefix.length) : "";
    if (ISSUE_NUMBER.test(rest)) return { page: id, issueId: Number(rest) };
  }
  return { page: "home", issueId: null };
}

export function pathFor(page, issueId = null) {
  const base = ROUTES[page] || ROUTES.dashboard;
  return issueId && ISSUE_PAGES.includes(page) ? `${base}/${issueId}` : base;
}

// A page with "roles" opens for those roles only; one without opens for anyone who is logged in.
// The backend decides who may do what; this only keeps people from pages that would refuse them.
// A page with "portal" belongs to the Super Admin portal, which has a navigation of its own.
const SUPER_ADMINS = ["super_admin"];
export const PAGES = {
  superAdmin: { label: "Super Admin", title: "Super Admin", subtitle: "Accounts, activity and today's numbers.", icon: ShieldCheck, roles: SUPER_ADMINS, portal: true },
  portalAdmins: { label: "Admins", title: "Admins", subtitle: "Who can log in, and what they may do.", icon: UserCog, roles: SUPER_ADMINS, portal: true },
  portalIssues: { label: "Issues", title: "Issues", subtitle: "Problems reported by admins.", icon: MessageSquareWarning, roles: SUPER_ADMINS, portal: true },
  portalAudit: { label: "Audit Log", title: "Audit Log", subtitle: "Who did what, and when.", icon: History, roles: SUPER_ADMINS, portal: true },
  changePassword: { label: "Change password", title: "Change password", subtitle: "Choose a new password for this account.", icon: KeyRound },
  dashboard: { label: "Dashboard", title: "Dashboard", subtitle: "Today's attendance at a glance.", icon: LayoutDashboard },
  scanner: { label: "Live Scanner", title: "Live Attendance", subtitle: "Start a session and point the camera at the class.", icon: ScanLine },
  enrollment: { label: "Face Enrollment", title: "Face Enrollment", subtitle: "Capture a student's reference faces, one pose at a time.", icon: ScanFace },
  reports: { label: "Reports", title: "Attendance Records", subtitle: "Filter attendance by course, batch and date.", icon: BarChart3 },
  students: { label: "Students", title: "Students", subtitle: "Students are assigned to a course and a batch.", icon: GraduationCap },
  staff: { label: "Staff", title: "Staff", subtitle: "Staff accounts kept alongside students.", icon: UserCheck },
  members: { label: "Members", title: "Members", subtitle: "Members kept alongside students.", icon: Users },
  courses: { label: "Courses", title: "Courses", subtitle: "Create a course before its batches and students.", icon: BookOpen },
  batches: { label: "Batches", title: "Batches", subtitle: "Every batch belongs to one course.", icon: Layers3 },
  myReports: { label: "My reports", title: "My reports", subtitle: "Problems you reported, and the answers to them.", icon: LifeBuoy },
  settings: { label: "Settings", title: "Settings", subtitle: "Connection and system status.", icon: Settings }
};

export const NAV_GROUPS = [
  { label: "Super Admin", items: ["superAdmin"] },
  { label: "Overview", items: ["dashboard"] },
  { label: "Manage", items: ["courses", "batches", "students", "staff", "members"] },
  { label: "Attendance", items: ["enrollment", "scanner", "reports"] },
  { label: "System", items: ["myReports", "settings"] }
];

// The portal's own navigation, with the way back to the console last.
export const PORTAL_NAV_GROUPS = [
  { label: "Super Admin", items: ["superAdmin", "portalAdmins", "portalIssues", "portalAudit"] },
  { label: "Console", items: ["dashboard"] }
];

export function isPortalPage(page) {
  return Boolean(PAGES[page]?.portal);
}

// The navigation one role sees on one page. An admin's console navigation is what it always was:
// the super admin group is simply absent, and the portal's pages never open for an admin.
export function navGroupsFor(role, page) {
  return visibleGroups(isPortalPage(page) ? PORTAL_NAV_GROUPS : NAV_GROUPS, PAGES, role);
}

// Inside the portal two entries go by other names: its own start page, and the way out of it.
const PORTAL_NAMES = { superAdmin: { label: "Dashboard" }, dashboard: { label: "Back to console", icon: ArrowLeft } };

export function navEntry(id, portal) {
  const page = PAGES[id];
  const renamed = portal ? PORTAL_NAMES[id] : null;
  return { label: renamed?.label || page.label, icon: renamed?.icon || page.icon };
}

// The phone bar shows four destinations around the scanner button; everything else is under "More".
// In the portal there is no scanner: its four pages, and the way back under "More".
export const MOBILE_NAV = { left: ["dashboard", "students"], center: "scanner", right: ["enrollment"] };
export const PORTAL_MOBILE_NAV = { left: ["superAdmin", "portalAdmins"], center: null, right: ["portalIssues", "portalAudit"] };

export const PERSON_CONFIG = {
  students: { title: "Students", singular: "Student", apiType: "student" },
  staff: { title: "Staff", singular: "Staff", apiType: "admin" },
  members: { title: "Members", singular: "Member", apiType: "member" }
};
