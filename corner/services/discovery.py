from corner.host_entry import main as _main


def main(argv=None):
    return _main('discovery', argv)


if __name__ == '__main__':
    raise SystemExit(main())
