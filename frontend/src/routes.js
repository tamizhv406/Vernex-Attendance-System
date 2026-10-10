import { BarChart3, BookOpen, GraduationCap, Layers3, LayoutDashboard, ScanFace, ScanLine, Settings, UserCheck, Users } from "lucide-react";

// The URLs are the ones the app already used; only how they are presented changed.
export const ROUTES = {
  dashboard: "/dashboard",
  courses: "/courses",
  batches: "/batches",
  students: "/users/students",
  staff: "/users/staff",
  members: "/users/members",
  enrollment: "/face-enrollment",
  scanner: "/attendance-scanner",
  reports: "/reports",
  settings: "/settings"
};

export const PATH_TO_PAGE = Object.fromEntries(Object.entries(ROUTES).map(([page, path]) => [path, page]));

export const PAGES = {
  dashboard: { label: "Dashboard", title: "Dashboard", subtitle: "Today's attendance at a glance.", icon: LayoutDashboard },
  scanner: { label: "Live Scanner", title: "Live Attendance", subtitle: "Start a session and point the camera at the class.", icon: ScanLine },
  enrollment: { label: "Face Enrollment", title: "Face Enrollment", subtitle: "Capture a student's reference faces, one pose at a time.", icon: ScanFace },
  reports: { label: "Reports", title: "Attendance Records", subtitle: "Filter attendance by course, batch and date.", icon: BarChart3 },
  students: { label: "Students", title: "Students", subtitle: "Students are assigned to a course and a batch.", icon: GraduationCap },
  staff: { label: "Staff", title: "Staff", subtitle: "Staff accounts kept alongside students.", icon: UserCheck },
  members: { label: "Members", title: "Members", subtitle: "Members kept alongside students.", icon: Users },
  courses: { label: "Courses", title: "Courses", subtitle: "Create a course before its batches and students.", icon: BookOpen },
  batches: { label: "Batches", title: "Batches", subtitle: "Every batch belongs to one course.", icon: Layers3 },
  settings: { label: "Settings", title: "Settings", subtitle: "Connection and system status.", icon: Settings }
};

export const NAV_GROUPS = [
  { label: "Overview", items: ["dashboard"] },
  { label: "Attendance", items: ["scanner", "enrollment", "reports"] },
  { label: "Manage", items: ["students", "staff", "members", "courses", "batches"] },
  { label: "System", items: ["settings"] }
];

// The phone bar shows four destinations around the scanner button; everything else is under "More".
export const MOBILE_NAV = { left: ["dashboard", "students"], center: "scanner", right: ["enrollment"] };

export const PERSON_CONFIG = {
  students: { title: "Students", singular: "Student", apiType: "student" },
  staff: { title: "Staff", singular: "Staff", apiType: "admin" },
  members: { title: "Members", singular: "Member", apiType: "member" }
};
