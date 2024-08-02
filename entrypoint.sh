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
            cd src
            bash
            ;;
        selfcheck)
            pytest src
            ;;
        start)
            printf "\t..: Starting the main service\n"
            exec python src/main.py
            ;;
        develop)
            printf "\t..: Starting the development loop\n"
            find src -name "*.py" | exec entr -rc python src/main.py
            ;;
        *)
            printf "\t..: Invoking '$@'\n"
            exec "$@"
            ;;
    esac
}

printf "\t..: Preparing $VERSION version on $CONTEXT\n"
main "$@"
