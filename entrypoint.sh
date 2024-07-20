#!/usr/bin/env bash
set -euo pipefail


main()
{
    first_arg=${1:-}
    case $first_arg in
        '')
            printf "\t..: Cannot start this container without any arguments\n"
            exit 1
            ;;
        shell)
            bash
            ;;
        start)
            printf "\t..: Starting the service.\n"
            ;;
        *)
            printf "\t..: Invoking '$@'\n"
            exec "$@"
            ;;
    esac
}

printf "\t..: Initializing $VERSION version on $CONTEXT\n"
main "$@"
